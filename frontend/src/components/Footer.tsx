export default function Footer() {
  const links = [
    { href: '#services', label: 'Research' },
    { href: '#about', label: 'About' },
    { href: '#contact', label: 'Contact' },
  ];

  return (
    <footer className="border-t border-slate-200 bg-slate-50">
      <div className="section-wrap py-12">
        <div className="flex flex-col md:flex-row md:justify-between md:items-start gap-8 mb-10">
          <div className="max-w-sm">
            <p className="font-semibold text-slate-900 mb-2">Alessar Solutions</p>
            <p className="text-sm text-slate-500 leading-relaxed">
              Market research agency. Surveys, focus groups, and field studies across multiple regions.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row gap-8 sm:gap-16">
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-3">Pages</p>
              <ul className="space-y-2">
                {links.map((link) => (
                  <li key={link.href}>
                    <a
                      href={link.href}
                      className="text-sm text-slate-600 hover:text-brand-700 transition-colors"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-3">Contact</p>
              <a
                href="mailto:support@alessarsolutions.in"
                className="text-sm text-slate-600 hover:text-brand-700 transition-colors"
              >
                support@alessarsolutions.in
              </a>
            </div>
          </div>
        </div>

        <div className="border-t border-slate-200 pt-6">
          <p className="text-sm text-slate-400">
            &copy; {new Date().getFullYear()} Alessar Solutions Pvt Ltd
          </p>
        </div>
      </div>
    </footer>
  );
}
