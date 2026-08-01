const technologies = [
  'React', 'Vue', 'Angular', 'Next.js', 'Node.js', 'Python', 'Django', 'Flask',
  'React Native', 'Flutter', 'Swift', 'Kotlin', 'Electron', 'TypeScript', 'JavaScript',
  'PostgreSQL', 'MongoDB', 'MySQL', 'Redis', 'AWS', 'Azure', 'Google Cloud', 'Docker',
  'Kubernetes', 'GraphQL', 'REST API', 'WebSocket', 'TailwindCSS', 'Material-UI',
  'Express', 'FastAPI', 'Firebase', 'Supabase', 'Git', 'CI/CD'
];

export default function Technologies() {
  return (
    <section className="py-20 bg-black">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-4xl md:text-5xl font-bold mb-4 bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">
            Technologies We Master
          </h2>
          <p className="text-xl text-gray-400 max-w-2xl mx-auto">
            Working with the latest and most powerful tools to build exceptional solutions
          </p>
        </div>

        <div className="flex flex-wrap justify-center gap-4">
          {technologies.map((tech, index) => (
            <div
              key={index}
              className="bg-gray-800/50 backdrop-blur-sm border border-gray-700 rounded-lg px-6 py-3 hover:bg-gray-800 hover:border-cyan-500/50 transition-all duration-300 hover:transform hover:scale-110"
            >
              <span className="text-gray-300 font-medium">{tech}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
