from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import datetime

from ee.db.payments.payments_enrollments import (
    EnrollmentStatusEnum,
    PaymentsEnrollment,
    PaymentsEnrollmentRead,
)
from ee.db.payments.payments_offers import PaymentsOffer
from ee.db.payments.payments_groups import PaymentsGroupSync
from src.db.organizations import Organization
from src.db.users import AnonymousUser, APITokenUser, InternalUser, PublicUser
from src.services.orgs.orgs import rbac_check
from src.services.users.usergroups import add_users_to_usergroup, remove_users_from_usergroup


async def create_enrollment(
    request: Request,
    org_id: int,
    offer_id: int,
    user_id: int,
    status: EnrollmentStatusEnum,
    provider_data: dict,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    db_session: AsyncSession,
) -> PaymentsEnrollment:
    org = (await db_session.exec(select(Organization).where(Organization.id == org_id))).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    await rbac_check(request, org.org_uuid, current_user, "create", db_session)

    offer = (await db_session.exec(
        select(PaymentsOffer).where(PaymentsOffer.id == offer_id, PaymentsOffer.org_id == org_id)
    )).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    existing = (await db_session.exec(
        select(PaymentsEnrollment).where(
            PaymentsEnrollment.user_id == user_id,
            PaymentsEnrollment.offer_id == offer_id,
            PaymentsEnrollment.org_id == org_id,
        )
    )).first()
    if existing:
        if existing.status in [EnrollmentStatusEnum.PENDING, EnrollmentStatusEnum.CANCELLED, EnrollmentStatusEnum.FAILED]:
            db_session.delete(existing)
            await db_session.commit()
        else:
            raise HTTPException(status_code=400, detail="User already has an active enrollment for this offer")

    enrollment = PaymentsEnrollment(
        offer_id=offer_id,
        user_id=user_id,
        org_id=org_id,
        status=status,
        provider_specific_data=provider_data or {},
        creation_date=datetime.now(),
        update_date=datetime.now(),
    )
    db_session.add(enrollment)
    await db_session.commit()
    await db_session.refresh(enrollment)
    return enrollment


async def update_enrollment_status(
    request: Request,
    org_id: int,
    enrollment_id: int,
    status: EnrollmentStatusEnum,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    db_session: AsyncSession,
) -> PaymentsEnrollment:
    """
    Central side-effect function for all enrollment status changes.

    ACTIVE/COMPLETED → add user to all UserGroups synced via the offer's PaymentsGroup
    CANCELLED/REFUNDED → remove user from those same UserGroups

    All webhooks and admin overrides must flow through this function.
    """
    org = (await db_session.exec(select(Organization).where(Organization.id == org_id))).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    await rbac_check(request, org.org_uuid, current_user, "update", db_session)

    enrollment = (await db_session.exec(
        select(PaymentsEnrollment).where(
            PaymentsEnrollment.id == enrollment_id,
            PaymentsEnrollment.org_id == org_id,
        )
    )).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    offer = (await db_session.exec(select(PaymentsOffer).where(PaymentsOffer.id == enrollment.offer_id))).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    old_status = enrollment.status
    enrollment.status = status
    enrollment.update_date = datetime.now()
    db_session.add(enrollment)
    await db_session.commit()
    await db_session.refresh(enrollment)

    # Determine synced UserGroups via the offer's PaymentsGroup
    synced_usergroup_ids: list[int] = []
    if offer.payments_group_id is not None:
        sync_rows = (await db_session.exec(
            select(PaymentsGroupSync).where(
                PaymentsGroupSync.payments_group_id == offer.payments_group_id
            )
        )).all()
        synced_usergroup_ids = [row.usergroup_id for row in sync_rows]

    active_statuses = {EnrollmentStatusEnum.ACTIVE, EnrollmentStatusEnum.COMPLETED}
    inactive_statuses = {EnrollmentStatusEnum.CANCELLED, EnrollmentStatusEnum.REFUNDED}

    for ug_id in synced_usergroup_ids:
        if status in active_statuses and old_status not in active_statuses:
            await add_users_to_usergroup(
                request=request,
                db_session=db_session,
                current_user=InternalUser(),
                usergroup_id=ug_id,
                user_ids=str(enrollment.user_id),
            )
        elif status in inactive_statuses and old_status in active_statuses:
            await remove_users_from_usergroup(
                request=request,
                db_session=db_session,
                current_user=InternalUser(),
                usergroup_id=ug_id,
                user_ids=str(enrollment.user_id),
            )

    return enrollment


async def get_enrollment(
    request: Request,
    org_id: int,
    enrollment_id: int,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    db_session: AsyncSession,
) -> PaymentsEnrollmentRead:
    org = (await db_session.exec(select(Organization).where(Organization.id == org_id))).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    await rbac_check(request, org.org_uuid, current_user, "read", db_session)

    enrollment = (await db_session.exec(
        select(PaymentsEnrollment).where(
            PaymentsEnrollment.id == enrollment_id,
            PaymentsEnrollment.org_id == org_id,
        )
    )).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return PaymentsEnrollmentRead.model_validate(enrollment)


async def list_enrollments(
    request: Request,
    org_id: int,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    db_session: AsyncSession,
) -> list[PaymentsEnrollmentRead]:
    org = (await db_session.exec(select(Organization).where(Organization.id == org_id))).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    await rbac_check(request, org.org_uuid, current_user, "read", db_session)

    enrollments = (await db_session.exec(
        select(PaymentsEnrollment)
        .where(PaymentsEnrollment.org_id == org_id)
        .order_by(PaymentsEnrollment.id.desc())  # type: ignore
    )).all()
    return [PaymentsEnrollmentRead.model_validate(e) for e in enrollments]


async def get_user_enrollments(
    request: Request,
    org_id: int,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    db_session: AsyncSession,
) -> list[dict]:
    if isinstance(current_user, AnonymousUser):
        return []

    results = (await db_session.exec(
        select(PaymentsEnrollment, PaymentsOffer)
        .join(PaymentsOffer, PaymentsEnrollment.offer_id == PaymentsOffer.id)  # type: ignore
        .where(
            PaymentsEnrollment.user_id == current_user.id,
            PaymentsEnrollment.org_id == org_id,
            PaymentsEnrollment.status.in_([EnrollmentStatusEnum.ACTIVE, EnrollmentStatusEnum.COMPLETED]),  # type: ignore
        )
    )).all()

    return [
        {
            "enrollment_id": enrollment.id,
            "offer_id": offer.id,
            "offer_name": offer.name,
            "offer_type": offer.offer_type,
            "amount": offer.amount,
            "currency": offer.currency,
            "payments_group_id": offer.payments_group_id,
            "status": enrollment.status,
            "creation_date": enrollment.creation_date,
        }
        for enrollment, offer in results
    ]


async def delete_enrollment(
    request: Request,
    org_id: int,
    enrollment_id: int,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    db_session: AsyncSession,
) -> None:
    org = (await db_session.exec(select(Organization).where(Organization.id == org_id))).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    await rbac_check(request, org.org_uuid, current_user, "delete", db_session)

    enrollment = (await db_session.exec(
        select(PaymentsEnrollment).where(
            PaymentsEnrollment.id == enrollment_id,
            PaymentsEnrollment.org_id == org_id,
        )
    )).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db_session.delete(enrollment)
    await db_session.commit()
