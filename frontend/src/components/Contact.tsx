import { Loader2, Mail } from 'lucide-react';
import { useState, useEffect, FormEvent, ChangeEvent } from 'react';

const checklist = [
  'The business question behind the study',
  'Countries or cities you need coverage in',
  'Audience type — consumers, B2B, etc.',
  'Preferred timeline, even if rough',
];

export default function Contact() {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    subject: '',
    message: '',
  });

  const [toast, setToast] = useState({
    show: false,
    type: '',
    text: '',
  });

  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (toast.show) {
      const timer = setTimeout(() => {
        setToast({ show: false, type: '', text: '' });
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const response = await fetch('https://www.serd-button.in/api/alessar-contact/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });

      const data = await response.json();

      if (data.status === 'success') {
        setToast({
          show: true,
          type: 'success',
          text: 'Got it — we will reply within a day or two.',
        });
        setFormData({ name: '', email: '', subject: '', message: '' });
      } else {
        setToast({
          show: true,
          type: 'error',
          text: 'Something went wrong. Please try again.',
        });
      }
    } catch (err) {
      setToast({
        show: true,
        type: 'error',
        text: 'Network error. Try again.',
      });
      console.error(err);
    }

    setLoading(false);
  };

  const handleChange = (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  return (
    <>
      {toast.show && (
        <div className="fixed top-5 right-5 z-50">
          <div
            className={`px-4 py-3 rounded-lg text-sm shadow-card ${
              toast.type === 'success'
                ? 'bg-slate-900 text-white'
                : 'bg-red-600 text-white'
            }`}
          >
            {toast.text}
          </div>
        </div>
      )}

      <section id="contact" className="py-20 md:py-24 bg-white">
        <div className="section-wrap">
          <div className="max-w-2xl mb-12">
            <h2 className="section-title mb-4">Get in touch</h2>
            <p className="section-lead">
              Tell us what you are trying to learn — target audience, markets, rough timeline. We will get back to you on whether we can help and what it would look like.
            </p>
          </div>

          <div className="grid lg:grid-cols-5 gap-10 lg:gap-14">
            <div className="lg:col-span-2 space-y-8">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-lg bg-brand-50 flex items-center justify-center shrink-0">
                  <Mail className="w-4 h-4 text-brand-700" />
                </div>
                <div>
                  <p className="font-medium text-slate-900 text-sm mb-1">Email</p>
                  <a
                    href="mailto:support@alessarsolutions.in"
                    className="text-sm text-slate-600 hover:text-brand-700 transition-colors"
                  >
                    support@alessarsolutions.in
                  </a>
                </div>
              </div>

              <div>
                <p className="font-medium text-slate-900 text-sm mb-3">What to include</p>
                <ul className="space-y-2">
                  {checklist.map((item) => (
                    <li key={item} className="text-sm text-slate-600 flex items-start gap-2">
                      <span className="text-brand-500 shrink-0">·</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <p className="text-sm text-slate-500">
                We usually respond within 1–2 working days.
              </p>
            </div>

            <form
              onSubmit={handleSubmit}
              className="lg:col-span-3 bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 shadow-card space-y-5"
            >
              <div className="grid sm:grid-cols-2 gap-5">
                <div>
                  <label htmlFor="name" className="block text-sm font-medium text-slate-700 mb-1.5">
                    Name
                  </label>
                  <input
                    type="text"
                    id="name"
                    name="name"
                    value={formData.name}
                    onChange={handleChange}
                    required
                    className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-500 bg-white"
                    placeholder="Your name"
                  />
                </div>

                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1.5">
                    Email
                  </label>
                  <input
                    type="email"
                    id="email"
                    name="email"
                    value={formData.email}
                    onChange={handleChange}
                    required
                    className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-500 bg-white"
                    placeholder="you@company.com"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="subject" className="block text-sm font-medium text-slate-700 mb-1.5">
                  Subject
                </label>
                <input
                  type="text"
                  id="subject"
                  name="subject"
                  value={formData.subject}
                  onChange={handleChange}
                  required
                  className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-500 bg-white"
                  placeholder="e.g. Product concept test in Mumbai & Delhi"
                />
              </div>

              <div>
                <label htmlFor="message" className="block text-sm font-medium text-slate-700 mb-1.5">
                  Message
                </label>
                <textarea
                  id="message"
                  name="message"
                  value={formData.message}
                  onChange={handleChange}
                  required
                  rows={5}
                  className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-500 bg-white resize-none"
                  placeholder="What do you need to find out, and who do you need to hear from?"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className={`text-sm font-medium px-6 py-3 rounded-lg transition-colors ${
                  loading
                    ? 'bg-slate-200 text-slate-500 cursor-not-allowed'
                    : 'bg-brand-700 text-white hover:bg-brand-600'
                }`}
              >
                {loading ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Sending…
                  </span>
                ) : (
                  'Send enquiry'
                )}
              </button>
            </form>
          </div>
        </div>
      </section>
    </>
  );
}
