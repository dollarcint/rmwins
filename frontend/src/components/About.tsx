const steps = [
  'You share the business question — not just a survey wish-list',
  'We propose method, sample size, timeline, and cost',
  'Fieldwork runs with regular check-ins along the way',
  'You receive findings with context, not raw tables only',
];

export default function About() {
  return (
    <section id="about" className="py-20 md:py-24 bg-slate-50 border-t border-slate-200/80">
      <div className="section-wrap">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-20">
          <div>
            <h2 className="section-title mb-6">About Alessar Solutions</h2>
            <div className="space-y-4 text-slate-600 leading-relaxed">
              <p>
                We started as a small team running field surveys and client interviews. Over time we built a respondent network across several regions and began taking on larger studies — product launches, category entry research, brand tracking.
              </p>
              <p>
                We are not a big consultancy with layers of account managers. You speak directly with the people running your study. That keeps timelines shorter and the feedback honest.
              </p>
              <p>
                Along the way we picked up development skills because clients often needed a place to host surveys, view results, or share reports. Today we are a research agency first, with technical work when it supports the project.
              </p>
            </div>
          </div>

          <div className="space-y-6">
            <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-soft">
              <h3 className="font-semibold text-slate-900 mb-4">How we work</h3>
              <ol className="space-y-3">
                {steps.map((step, i) => (
                  <li key={step} className="flex gap-3 text-sm text-slate-600">
                    <span className="shrink-0 w-6 h-6 rounded-full bg-brand-50 text-brand-700 text-xs font-semibold flex items-center justify-center">
                      {i + 1}
                    </span>
                    <span className="pt-0.5 leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
            </div>

            <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-soft">
              <h3 className="font-semibold text-slate-900 mb-3">Who we work with</h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                FMCG brands, startups testing a new market, agencies that need field support, and companies expanding from one country to another. If you need opinions from real people in specific regions, that is usually us.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
