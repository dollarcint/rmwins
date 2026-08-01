import { useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Linkedin, Github, Mail } from 'lucide-react';

const teamMembers = [
  {
    id: 2,
    name: 'Vanshika Gupta',
    role: 'Co-Founder',
    description: 'She leads client interactions, handles meetings, and ensures smooth day-to-day operations.With a people-first approach, she bridges the gap between clients and the development team, making sure every project runs on track and every client stays informed and satisfied.',
    image: '/team/vanshika.jpeg',
    linkedin: 'https://www.linkedin.com/in/bunny0522/',
    github: 'https://github.com/kanik-snippet',
    email: 'mailto:guptavanshika256@gmail.com',
  },
  {
    id: 3,
    name: 'Akanksha',
    role: 'Co-Founder',
    description: 'Co-Founder with solid expertise in frontend development. Experienced in creating clean, responsive, and user-friendly interfaces, with a strong focus on performance and modern UI practices.',
    image: '/team/akanksha.png',
    linkedin: 'https://www.linkedin.com/in/bunny0522/',
    github: 'https://github.com/kanik-snippet',
    email: 'mailto:kashyapakanksha0507@gmail.com',
  },
  {
    id: 1,
    name: 'Kanik Gupta',
    role: 'Founder & CEO',
    description: 'Founder & CEO with strong hands-on experience as a Senior Developer. Skilled in building scalable web applications and leading technical teams, with deep expertise across modern backend and full-stack technologies.',
    image: '/team/kanik.jpeg',
    linkedin: 'https://www.linkedin.com/in/bunny0522/',
    github: 'https://github.com/kanik-snippet',
    email: 'mailto:kanik@alessarsolutions.in',
  },
  {
  id: 5,
  name: 'Aastha Dixit',
  role: 'Lead Developer',
  description: 'Backend Developer with strong knowledge of server-side architecture, databases, and APIs. Focused on building secure, efficient, and scalable backend systems.',
  image: '/team/aastha.jpeg',
  linkedin: 'https://www.linkedin.com/in/aastha-dixit-958065210/',
  github: 'https://github.com/kanik-snippet',
  email: 'mailto:aaasthadixit@gmail.com',
},
  {
    id: 4,
    name: 'Surya Singh',
    role: 'HR Manager',
    description: 'HR Manager known for excellent communication skills and a positive personality. Passionate about people management, team culture, and building a healthy, collaborative work environment.',
    image: '/team/surya.png',
    linkedin: 'https://www.linkedin.com/in/suryasingh2701/',
    github: 'https://github.com/Surya-2701',
    email: 'mailto:suryapratap2701@gmail.com',
  },
  {
    id: 6,
    name: 'Aayushi Sharma',
    role: 'Marketing Expert',
    description: 'Backend Developer with strong knowledge of server-side architecture, databases, and APIs. Focused on building secure, efficient, and scalable backend systems.',
    image: '/team/aayushi.jpeg',
    linkedin: 'https://www.linkedin.com/in/bunny0522/',
    github: 'https://github.com/kanik-snippet',
    email: 'mailto:kanik@alessarsolutions.in',
  },

  {
    id: 7,
    name: 'Anushka',
    role: 'Backend Engineer',
    description: 'Backend Developer with strong knowledge of server-side architecture, databases, and APIs. Focused on building secure, efficient, and scalable backend systems.',
    image: '/team/anushka.jpeg',
    linkedin: 'https://www.linkedin.com/in/bunny0522/',
    github: 'https://github.com/kanik-snippet',
    email: 'mailto:kanik@alessarsolutions.in',
  },

];

export default function Team() {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showLeftArrow, setShowLeftArrow] = useState(false);
  const [showRightArrow, setShowRightArrow] = useState(true);

  const handleScroll = () => {
    if (!scrollContainerRef.current) return;

    const { scrollLeft, scrollWidth, clientWidth } = scrollContainerRef.current;
    setShowLeftArrow(scrollLeft > 0);
    setShowRightArrow(scrollLeft < scrollWidth - clientWidth - 10);
  };

  const scroll = (direction: 'left' | 'right') => {
    if (!scrollContainerRef.current) return;

    const scrollAmount = 400;
    scrollContainerRef.current.scrollBy({
      left: direction === 'left' ? -scrollAmount : scrollAmount,
      behavior: 'smooth',
    });
  };

  return (
    <section className="py-20 bg-gradient-to-b from-black to-gray-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-4xl md:text-5xl font-bold mb-4 bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">
            Meet Our Team
          </h2>
          <p className="text-xl text-gray-400 max-w-2xl mx-auto">
            Talented professionals dedicated to delivering excellence and innovation
          </p>
        </div>

        <div className="relative">
          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="flex overflow-x-auto gap-6 pb-4 scrollbar-hide"
            style={{
              scrollBehavior: 'smooth',
              scrollbarWidth: 'none',
              msOverflowStyle: 'none',
            }}
          >
            {teamMembers.map((member) => (
              <div
                key={member.id}
                className="flex-shrink-0 w-72 group"
              >
                <div className="bg-gray-800/50 backdrop-blur-sm border border-gray-700 rounded-2xl overflow-hidden hover:border-cyan-500/50 transition-all duration-300 hover:transform hover:scale-105 h-full flex flex-col">
                  <div className="h-72 relative overflow-hidden">
                    <img
                      src={member.image}
                      alt={member.name}
                      className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-500"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-gray-900 via-transparent to-transparent"></div>
                  </div>

                  <div className="px-6 py-6 flex flex-col flex-grow">
                    <h3 className="text-xl font-semibold text-white mb-1 group-hover:text-cyan-400 transition-colors">
                      {member.name}
                    </h3>
                    <p className="text-cyan-400 text-sm font-medium mb-3">
                      {member.role}
                    </p>

                    <p className="text-gray-400 text-sm leading-relaxed flex-grow mb-4">
                      {member.description}
                    </p>

                    <div className="flex space-x-3 pt-4 border-t border-gray-700">
  <a
    href={member.linkedin}
    target="_blank"
    className="flex-1 bg-gray-700/50 hover:bg-gray-700 rounded-lg p-2 flex items-center justify-center transition-colors text-gray-400 hover:text-cyan-400"
  >
    <Linkedin className="w-4 h-4" />
  </a>

  {member.github && (
    <a
      href={member.github}
      target="_blank"
      className="flex-1 bg-gray-700/50 hover:bg-gray-700 rounded-lg p-2 flex items-center justify-center transition-colors text-gray-400 hover:text-cyan-400"
    >
      <Github className="w-4 h-4" />
    </a>
  )}

  <a
    href={member.email}
    className="flex-1 bg-gray-700/50 hover:bg-gray-700 rounded-lg p-2 flex items-center justify-center transition-colors text-gray-400 hover:text-cyan-400"
  >
    <Mail className="w-4 h-4" />
  </a>
</div>

                  </div>
                </div>
              </div>
            ))}
          </div>

          {showLeftArrow && (
            <button
              onClick={() => scroll('left')}
              className="absolute left-0 top-1/2 transform -translate-y-1/2 -translate-x-4 z-10 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white p-3 rounded-full shadow-lg transition-all duration-300 hover:scale-110"
            >
              <ChevronLeft className="w-6 h-6" />
            </button>
          )}

          {showRightArrow && (
            <button
              onClick={() => scroll('right')}
              className="absolute right-0 top-1/2 transform -translate-y-1/2 translate-x-4 z-10 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white p-3 rounded-full shadow-lg transition-all duration-300 hover:scale-110"
            >
              <ChevronRight className="w-6 h-6" />
            </button>
          )}
        </div>

        <p className="text-center text-gray-500 text-sm mt-8">
          Scroll to see more team members →
        </p>
      </div>
    </section>
  );
}
