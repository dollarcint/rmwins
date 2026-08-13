import { AlertTriangle, CheckCircle2, Info, ShieldX } from 'lucide-react';

const outcomes = {
  '1': {
    title: 'Survey completed',
    message: 'Thank you. Your survey response has been completed successfully.',
    icon: CheckCircle2,
    color: 'text-emerald-600',
    surface: 'bg-emerald-50',
  },
  '2': {
    title: 'Survey terminated',
    message: 'The survey ended before your response could be completed.',
    icon: Info,
    color: 'text-slate-600',
    surface: 'bg-slate-100',
  },
  '3': {
    title: 'Quota full',
    message: 'The required quota was filled before your response could be completed.',
    icon: AlertTriangle,
    color: 'text-amber-600',
    surface: 'bg-amber-50',
  },
  '4': {
    title: 'Quality check unsuccessful',
    message: "This response did not pass the survey's quality checks.",
    icon: ShieldX,
    color: 'text-rose-600',
    surface: 'bg-rose-50',
  },
} as const;

export default function SurveyStatusPage() {
  const params = new URLSearchParams(window.location.search);
  const status = params.get('status') || '';
  const rid = params.get('rid') || '';
  const outcome = outcomes[status as keyof typeof outcomes];

  if (!outcome || !/^[A-Za-z0-9]{10}$/.test(rid)) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-5">
        <section className="w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-card">
          <AlertTriangle className="mx-auto h-14 w-14 text-amber-600" />
          <h1 className="mt-5 text-2xl font-semibold text-slate-900">Invalid survey result</h1>
          <p className="mt-3 text-slate-600">A valid survey status and RID are required.</p>
        </section>
      </main>
    );
  }

  const Icon = outcome.icon;
  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-brand-50 px-5 py-12">
      <section className="w-full max-w-xl rounded-3xl border border-slate-200/80 bg-white p-8 text-center shadow-card sm:p-12">
        <div className={`mx-auto flex h-20 w-20 items-center justify-center rounded-full ${outcome.surface}`}>
          <Icon className={`h-10 w-10 ${outcome.color}`} strokeWidth={1.8} />
        </div>
        <p className="mt-7 text-sm font-semibold uppercase tracking-[0.18em] text-brand-600">Survey status</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">{outcome.title}</h1>
        <p className="mx-auto mt-4 max-w-md text-lg leading-relaxed text-slate-600">{outcome.message}</p>
        <div className="mt-8 rounded-2xl bg-slate-50 px-5 py-4 text-left">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">RID</span>
          <p className="mt-1 font-mono text-sm font-medium text-slate-800">{rid}</p>
        </div>
        <p className="mt-7 text-sm text-slate-500">Your result has been recorded. You may safely close this window.</p>
      </section>
    </main>
  );
}
