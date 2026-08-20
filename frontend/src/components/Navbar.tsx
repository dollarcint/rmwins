import { LogIn, Menu, X } from 'lucide-react';
import { useState } from 'react';

const dashboardLoginUrl = '/login';

const links = [
  { id: 'home', label: 'Home' },
  { id: 'services', label: 'Research' },
  { id: 'about', label: 'About' },
  { id: 'contact', label: 'Contact' },
];

export default function Navbar() {
  const [isOpen, setIsOpen] = useState(false);

  const scrollToSection = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
    setIsOpen(false);
  };

  return (
    <nav className="fixed w-full top-0 z-50 bg-white/90 backdrop-blur-md border-b border-slate-100 shadow-sm shadow-slate-900/5">
      <div className="section-wrap">
        <div className="flex justify-between items-center h-16">
          <button
            onClick={() => scrollToSection('home')}
            className="text-lg font-semibold text-slate-900 hover:text-brand-700 transition-colors"
          >
            Enligne Surveys
          </button>

          <div className="hidden md:flex items-center gap-8">
            {links.slice(1).map((link) => (
              <button
                key={link.id}
                onClick={() => scrollToSection(link.id)}
                className="text-sm text-slate-600 hover:text-slate-900 transition-colors"
              >
                {link.label}
              </button>
            ))}
            <div className="flex items-center gap-2">
              <button
                onClick={() => scrollToSection('contact')}
                className="text-sm bg-brand-700 text-white px-4 py-2 rounded-lg font-medium hover:bg-brand-600 transition-colors"
              >
                Request a study
              </button>
              <a
                href={dashboardLoginUrl}
                className="inline-flex items-center gap-1.5 text-sm border border-slate-200 text-slate-700 px-3.5 py-2 rounded-lg font-medium hover:border-brand-500 hover:text-brand-700 hover:bg-brand-50 transition-colors"
              >
                <LogIn size={15} />
                Login
              </a>
            </div>
          </div>

          <button
            onClick={() => setIsOpen(!isOpen)}
            className="md:hidden text-slate-600 hover:text-slate-900 p-1"
            aria-label="Menu"
            aria-expanded={isOpen}
          >
            {isOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>
      </div>

      {isOpen && (
        <div className="md:hidden border-t border-slate-100 bg-white">
          <div className="section-wrap py-4 space-y-1">
            {links.map((link) => (
              <button
                key={link.id}
                onClick={() => scrollToSection(link.id)}
                className="block w-full text-left py-2.5 text-sm text-slate-700 hover:text-brand-700"
              >
                {link.label}
              </button>
            ))}
            <button
              onClick={() => scrollToSection('contact')}
              className="w-full mt-2 bg-brand-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium"
            >
              Request a study
            </button>
            <a
              href={dashboardLoginUrl}
              className="flex items-center justify-center gap-2 w-full border border-slate-200 text-slate-700 px-4 py-2.5 rounded-lg text-sm font-medium hover:border-brand-500 hover:text-brand-700 hover:bg-brand-50 transition-colors"
            >
              <LogIn size={16} />
              Login
            </a>
          </div>
        </div>
      )}
    </nav>
  );
}
