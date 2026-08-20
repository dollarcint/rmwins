import About from './About';
import Contact from './Contact';
import Footer from './Footer';
import Hero from './Hero';
import Navbar from './Navbar';
import Services from './Services';

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <Navbar />
      <Hero />
      <Services />
      <About />
      <Contact />
      <Footer />
    </div>
  );
}
