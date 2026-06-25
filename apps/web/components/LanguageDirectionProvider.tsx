'use client'; // Required for Next.js App Router if they are using it

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next'; // Learnhouse's translation library

export default function LanguageDirectionProvider({ children }: { children: React.ReactNode }) {
  // Grab the i18n instance
  const { i18n } = useTranslation(); 

  useEffect(() => {
    // Safety check in case it's not loaded yet
    if (!i18n || !i18n.language) return;

    // 1. Define RTL languages
    const rtlLanguages = ['fa', 'ar', 'he'];
    
    // 2. Get the base language (e.g., changes 'fa-IR' to 'fa' just in case)
    const currentLang = i18n.language.split('-')[0];
    
    // 3. Check if the current language is RTL
    const isRtl = rtlLanguages.includes(currentLang);
    
    // 4. Update the HTML tag dynamically!
    document.documentElement.dir = isRtl ? 'rtl' : 'ltr';
    document.documentElement.lang = currentLang;
    
  }, [i18n.language]); // This runs EVERY time the user changes the language

  return <>{children}</>;
}