from typing import Literal
from fastapi import HTTPException, Request
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from ee.db.payments.payments import (
    PaymentProviderEnum,
    PaymentsConfig,
    PaymentsConfigUpdate,
    PaymentsConfigRead,
)
from src.db.users import PublicUser, AnonymousUser, InternalUser, APITokenUser
from src.db.organizations import Organization
from src.services.orgs.orgs import rbac_check


async def init_payments_config(
    request: Request,
    org_id: int,
    provider: Literal["stripe"],
    current_user: PublicUser | AnonymousUser | APITokenUser,
    db_session: AsyncSession,
) -> PaymentsConfig:
    # Validate organization exists
    org = (await db_session.exec(
        select(Organization).where(Organization.id == org_id)
    )).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Verify permissions
    await rbac_check(request, org.org_uuid, current_user, "create", db_session)

    # Check for existing config
    existing_config = (await db_session.exec(
        select(PaymentsConfig).where(PaymentsConfig.org_id == org_id)
    )).first()

    if existing_config:
        raise HTTPException(
            status_code=409,
            detail="Payments config already exists for this organization"
        )

    # Map the string provider name to the enum value
    try:
        provider_enum = PaymentProviderEnum(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported payment provider: {provider}")

    # Initialize new config — provider_config starts empty; each provider's
    # service layer is responsible for populating it during its own setup flow.
    new_config = PaymentsConfig(
        org_id=org_id,
        provider=provider_enum,
        provider_config={},
        provider_specific_id=None
    )

    # Save to database
    db_session.add(new_config)
    await db_session.commit()
    await db_session.refresh(new_config)

    return new_config


async def get_payments_config(
    request: Request,
    org_id: int,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    db_session: AsyncSession,
) -> list[PaymentsConfigRead]:
    # Check if organization exists
    statement = select(Organization).where(Organization.id == org_id)
    org = (await db_session.exec(statement)).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # RBAC check
    await rbac_check(request, org.org_uuid, current_user, "read", db_session)

    # Get payments config
    statement = select(PaymentsConfig).where(PaymentsConfig.org_id == org_id)
    configs = (await db_session.exec(statement)).all()

    return [PaymentsConfigRead.model_validate(config) for config in configs]


async def update_payments_config(
    request: Request,
    org_id: int,
    payments_config: PaymentsConfigUpdate,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    db_session: AsyncSession,
) -> PaymentsConfig:
    # Check if organization exists
    statement = select(Organization).where(Organization.id == org_id)
    org = (await db_session.exec(statement)).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # RBAC check
    await rbac_check(request, org.org_uuid, current_user, "update", db_session)

    # Get existing payments config
    statement = select(PaymentsConfig).where(PaymentsConfig.org_id == org_id)
    config = db_session.exec(statement).first()
    if not config:
        raise HTTPException(status_code=404, detail="Payments config not found")

    # Update config
    for key, value in payments_config.model_dump(exclude_unset=True).items():
        setattr(config, key, value)

    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    return config


async def delete_payments_config(
    request: Request,
    org_id: int,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    db_session: AsyncSession,
) -> None:
    # Check if organization exists
    statement = select(Organization).where(Organization.id == org_id)
    org = (await db_session.exec(statement)).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # RBAC check
    await rbac_check(request, org.org_uuid, current_user, "delete", db_session)

    # Get existing payments config
    statement = select(PaymentsConfig).where(PaymentsConfig.org_id == org_id)
    config = (await db_session.exec(statement)).first()
    if not config:
        raise HTTPException(status_code=404, detail="Payments config not found")

    # Guard: block disconnect when active subscriptions exist
    try:
        from ee.db.payments.payments_offers import PaymentsOffer, OfferTypeEnum
        from ee.db.payments.payments_enrollments import PaymentsEnrollment, EnrollmentStatusEnum

        active_sub_count = (await db_session.exec(
            select(func.count(PaymentsEnrollment.id))
            .join(PaymentsOffer, PaymentsEnrollment.offer_id == PaymentsOffer.id)  # type: ignore
            .where(
                PaymentsOffer.payments_config_id == config.id,
                PaymentsEnrollment.status == EnrollmentStatusEnum.ACTIVE,
                PaymentsOffer.offer_type == OfferTypeEnum.SUBSCRIPTION,
            )
        )).one()

        if active_sub_count > 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ACTIVE_SUBSCRIPTIONS_EXIST",
                    "count": active_sub_count,
                    "message": "Cancel all active subscriptions before disconnecting.",
                },
            )
    except HTTPException:
        raise
    except Exception:
        pass  # payments module not available — skip silently

    # Delete config
    db_session.delete(config)
    await db_session.commit()
