import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

export interface QuoteForm {
  destination: string;
  start: string;
  end: string;
  travellers: number;
  ages: string[];
  citizenship: string;
  residence: string;
  name: string;
  email: string;
  dial: string;
  phone: string;
  purpose: string;
  preExisting: 'no' | 'yes';
  consent: boolean;
}

const initialForm: QuoteForm = {
  destination: 'Canada',
  start: '',
  end: '',
  travellers: 2,
  ages: ['', ''],
  citizenship: 'India',
  residence: 'India',
  name: '',
  email: '',
  dial: '+91',
  phone: '',
  purpose: 'Visiting family',
  preExisting: 'no',
  consent: true,
};

interface QuoteContextValue {
  form: QuoteForm;
  setForm: (patch: Partial<QuoteForm>) => void;
  setAge: (index: number, value: string) => void;
  setTravellers: (n: number) => void;
  addTraveller: () => void;
  removeTraveller: (index: number) => void;

  quoteOpen: boolean;
  step: 1 | 2 | 3;
  goStep: (n: 1 | 2 | 3) => void;
  openQuote: (patch?: Partial<QuoteForm>, autoAdvance?: boolean) => void;
  closeQuote: () => void;

  consultOpen: boolean;
  openConsult: () => void;
  closeConsult: () => void;
}

const QuoteContext = createContext<QuoteContextValue | null>(null);

export function QuoteProvider({ children }: { children: ReactNode }) {
  const [form, setFormState] = useState<QuoteForm>(initialForm);
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [consultOpen, setConsultOpen] = useState(false);

  const setForm = useCallback((patch: Partial<QuoteForm>) => {
    setFormState((f) => ({ ...f, ...patch }));
  }, []);

  const MAX_TRAVELLERS = 8;

  /** travellers is kept in step with the ages list, which is what the form edits. */
  const setTravellers = useCallback((n: number) => {
    setFormState((f) => {
      const travellers = Math.min(MAX_TRAVELLERS, Math.max(1, n));
      const ages = Array.from({ length: travellers }, (_, i) => f.ages[i] ?? '');
      return { ...f, travellers, ages };
    });
  }, []);

  const addTraveller = useCallback(() => {
    setFormState((f) => {
      if (f.ages.length >= MAX_TRAVELLERS) return f;
      const ages = [...f.ages, ''];
      return { ...f, ages, travellers: ages.length };
    });
  }, []);

  const removeTraveller = useCallback((index: number) => {
    setFormState((f) => {
      if (f.ages.length <= 1) return f;
      const ages = f.ages.filter((_, i) => i !== index);
      return { ...f, ages, travellers: ages.length };
    });
  }, []);

  const setAge = useCallback((index: number, value: string) => {
    setFormState((f) => {
      const ages = [...f.ages];
      ages[index] = value;
      return { ...f, ages };
    });
  }, []);

  const goStep = useCallback((n: 1 | 2 | 3) => setStep(n), []);

  const openQuote = useCallback((patch?: Partial<QuoteForm>, autoAdvance = false) => {
    if (patch) setForm(patch);
    setStep(autoAdvance ? 3 : 1);
    setQuoteOpen(true);
  }, [setForm]);

  const closeQuote = useCallback(() => setQuoteOpen(false), []);
  const openConsult = useCallback(() => setConsultOpen(true), []);
  const closeConsult = useCallback(() => setConsultOpen(false), []);

  const value = useMemo<QuoteContextValue>(
    () => ({
      form, setForm, setAge, setTravellers, addTraveller, removeTraveller,
      quoteOpen, step, goStep, openQuote, closeQuote,
      consultOpen, openConsult, closeConsult,
    }),
    [form, setForm, setAge, setTravellers, addTraveller, removeTraveller, quoteOpen, step, goStep, openQuote, closeQuote, consultOpen, openConsult, closeConsult],
  );

  return <QuoteContext.Provider value={value}>{children}</QuoteContext.Provider>;
}

export function useQuote() {
  const ctx = useContext(QuoteContext);
  if (!ctx) throw new Error('useQuote must be used within QuoteProvider');
  return ctx;
}
