const researchServices = [
  {
    title: 'Consumer surveys',
    description: 'Online and phone surveys with screened respondents. Questionnaire design, fielding, and cleaned data delivery.',
  },
  {
    title: 'Focus groups & IDIs',
    description: 'Moderated sessions in local languages. For when you need the why behind the numbers.',
  },
  {
    title: 'Brand & product testing',
    description: 'Concept tests, packaging feedback, ad testing — before you commit budget to a launch.',
  },
  {
    title: 'Competitive landscape',
    description: 'Category mapping, pricing, and buyer behaviour in markets you are entering or growing in.',
  },
  {
    title: 'Field research',
    description: 'On-ground data collection in cities and towns where desk research falls short.',
  },
  {
    title: 'Reporting & analysis',
    description: 'Findings written up with recommendations — not just tables exported to Excel.',
  },
];

const otherServices = [
  'Web & mobile app development',
  'Custom dashboards for research data',
  'UI/UX design',
  'Data analysis & reporting',
  'API & backend development',
  'Cloud setup & maintenance',
];

export default function Services() {
  return (
    <section id="services" className="py-20 md:py-24 bg-white">
      <div className="section-wrap">
        <div className="max-w-2xl mb-14">
          <h2 className="section-title mb-4">What we do</h2>
          <p className="section-lead">
            Market research is our main focus. Most of what we do is surveys, interviews, and field studies — scoped, run, and reported end to end.
          </p>
        </div>

        <p className="text-xs font-semibold uppercase tracking-wider text-brand-700 mb-6">
          Core research services
        </p>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5 mb-14">
          {researchServices.map((service) => (
            <div
              key={service.title}
              className="bg-white border border-slate-200 rounded-xl p-5 hover:border-brand-100 hover:shadow-soft transition-all"
            >
              <h3 className="font-semibold text-slate-900 mb-2">{service.title}</h3>
              <p className="text-sm text-slate-600 leading-relaxed">{service.description}</p>
            </div>
          ))}
        </div>

        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-6 sm:p-8">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-5">
            <div>
              <h3 className="font-semibold text-slate-900 mb-1">Additional services</h3>
              <p className="text-sm text-slate-600 leading-relaxed max-w-xl">
                We also build portals, dashboards, and tools when a research project needs them. Development work usually supports a study — it is not our primary offering.
              </p>
            </div>
            <span className="shrink-0 text-xs font-medium text-slate-500 bg-white border border-slate-200 px-3 py-1 rounded-full">
              Supporting capability
            </span>
          </div>

          <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
            {otherServices.map((item) => (
              <li key={item} className="text-sm text-slate-600 flex items-start gap-2">
                <span className="text-brand-500 mt-0.5 shrink-0">·</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
