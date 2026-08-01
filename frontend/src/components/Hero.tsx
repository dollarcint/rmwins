export default function Hero() {
  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  };

  const regions = ['India', 'Southeast Asia', 'Middle East', 'United Kingdom', 'North America'];

  return (
    <section id="home" className="relative pt-28 pb-20 md:pt-36 md:pb-28 bg-white overflow-hidden">
      <div className="absolute top-0 right-0 w-[480px] h-[480px] bg-brand-50 rounded-full blur-3xl opacity-70 -translate-y-1/3 translate-x-1/4 pointer-events-none" />

      <div className="section-wrap relative">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          <div>
            <span className="inline-block text-xs font-medium uppercase tracking-wider text-brand-700 bg-brand-50 px-3 py-1 rounded-full mb-6">
              Market research agency
            </span>

            <h1 className="text-4xl sm:text-5xl lg:text-[3.25rem] font-semibold text-slate-900 leading-[1.1] tracking-tight mb-6">
              Real opinions from real markets.
            </h1>

            <p className="text-lg text-slate-600 leading-relaxed mb-4">
              Alessar Solutions runs surveys, focus groups, and field research for clients who need to understand audiences across regions — not guess at them.
            </p>

            <p className="text-base text-slate-500 leading-relaxed mb-8">
              We work with brands, agencies, and growing businesses that want clear answers they can actually use.
            </p>

            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => scrollTo('contact')}
                className="bg-brand-700 text-white px-6 py-3 rounded-lg text-sm font-medium hover:bg-brand-600 transition-colors"
              >
                Request a study
              </button>
              <button
                onClick={() => scrollTo('services')}
                className="border border-slate-200 text-slate-700 px-6 py-3 rounded-lg text-sm font-medium hover:border-slate-300 hover:bg-slate-50 transition-colors"
              >
                What we do
              </button>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 shadow-card">
            <p className="text-sm font-medium text-slate-900 mb-5">Where we field research</p>
            <div className="flex flex-wrap gap-2">
              {regions.map((region) => (
                <span
                  key={region}
                  className="text-sm text-slate-700 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg"
                >
                  {region}
                </span>
              ))}
            </div>
            <p className="text-sm text-slate-500 mt-6 leading-relaxed">
              More regions added when client projects need them.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
