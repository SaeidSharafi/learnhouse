import { useTranslation } from 'react-i18next';

// Centralized list of RTL languages
const rtlLanguages = ['fa', 'ar', 'he', 'ur'];

export function useIsRtl(): boolean {
  const { i18n } = useTranslation();
  
  // Safely get the current language, fallback to 'en' if not loaded
  const currentLang = (i18n?.language || 'en').split('-')[0];
  
  // Return true if Farsi/Arabic/etc, false if English/French/etc.
  return rtlLanguages.includes(currentLang);
}