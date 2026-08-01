import { Shield, Radio, Video, Wifi, Bell, CheckCircle, ExternalLink } from 'lucide-react';

export default function Products() {
  return (
    <section id="products" className="py-20 bg-gradient-to-b from-gray-900 to-black">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-4xl md:text-5xl font-bold mb-4 bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">
            Featured Product
          </h2>
          <p className="text-xl text-gray-400 max-w-2xl mx-auto">
            Innovative solutions that make a difference
          </p>
        </div>

        <div className="bg-gradient-to-br from-gray-800 to-gray-900 border border-gray-700 rounded-2xl overflow-hidden">
          <div className="grid md:grid-cols-2 gap-8">
            <div className="p-8 md:p-12">
              <div className="inline-flex items-center space-x-2 bg-red-600/20 border border-red-500/30 rounded-full px-4 py-2 mb-6">
                <Shield className="w-4 h-4 text-red-400" />
                <span className="text-sm text-red-400">Emergency Safety System</span>
              </div>

              <h3 className="text-3xl md:text-4xl font-bold mb-4 text-white">
                Smart Emegency Response Device
              </h3>

              <p className="text-gray-300 mb-6 text-lg">
                Emergency Trigger - Your lifeline in critical situations. A comprehensive emergency alert system designed to keep you safe by instantly notifying trusted contacts when you need help most.
              </p>

              <div className="space-y-4 mb-8">
                <div className="flex items-start space-x-3">
                  <Bell className="w-5 h-5 text-cyan-400 mt-1 flex-shrink-0" />
                  <div>
                    <h4 className="text-white font-semibold">Multi-Channel Alerts</h4>
                    <p className="text-gray-400 text-sm">SMS, WhatsApp, email, and voice calls to multiple contacts instantly</p>
                  </div>
                </div>

                <div className="flex items-start space-x-3">
                  <Video className="w-5 h-5 text-cyan-400 mt-1 flex-shrink-0" />
                  <div>
                    <h4 className="text-white font-semibold">Audio & Video Recording</h4>
                    <p className="text-gray-400 text-sm">Real-time recording and streaming during emergencies</p>
                  </div>
                </div>

                <div className="flex items-start space-x-3">
                  <Wifi className="w-5 h-5 text-cyan-400 mt-1 flex-shrink-0" />
                  <div>
                    <h4 className="text-white font-semibold">Easy Wi-Fi Setup</h4>
                    <p className="text-gray-400 text-sm">Simple configuration with hotspot mode and LED indicators</p>
                  </div>
                </div>

                <div className="flex items-start space-x-3">
                  <Radio className="w-5 h-5 text-cyan-400 mt-1 flex-shrink-0" />
                  <div>
                    <h4 className="text-white font-semibold">Reliable in Low Connectivity</h4>
                    <p className="text-gray-400 text-sm">Works efficiently even in areas with poor network coverage</p>
                  </div>
                </div>

                <div className="flex items-start space-x-3">
                  <CheckCircle className="w-5 h-5 text-cyan-400 mt-1 flex-shrink-0" />
                  <div>
                    <h4 className="text-white font-semibold">"All is Well" Feature</h4>
                    <p className="text-gray-400 text-sm">Send reassuring updates to contacts when everything is okay</p>
                  </div>
                </div>
              </div>

              <a
                href="https://serdevice.xyz"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center space-x-2 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white px-6 py-3 rounded-lg font-semibold transition-all duration-300 transform hover:scale-105"
              >
                <span>Visit Smart Emegency Response Device.xyz</span>
                <ExternalLink className="w-5 h-5" />
              </a>
            </div>

            <div className="relative bg-gradient-to-br from-blue-600/20 to-cyan-600/20 p-8 md:p-12 flex items-center justify-center">
              <div className="relative w-full max-w-sm">
                <div className="absolute inset-0 bg-gradient-to-r from-blue-600 to-cyan-600 rounded-full blur-3xl opacity-30 animate-pulse"></div>
                <div className="relative bg-gray-900 rounded-2xl p-8 border border-cyan-500/30">
                  <div className="text-center mb-6">
                    <Shield className="w-24 h-24 mx-auto text-cyan-400 mb-4" />
                    <h4 className="text-2xl font-bold text-white mb-2">Smart Emegency Response Device</h4>
                    <p className="text-cyan-400">Emergency Trigger System</p>
                  </div>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between bg-gray-800 rounded-lg p-3">
                      <span className="text-gray-400">Status</span>
                      <span className="text-green-400 font-semibold">Active</span>
                    </div>
                    <div className="flex items-center justify-between bg-gray-800 rounded-lg p-3">
                      <span className="text-gray-400">Response Time</span>
                      <span className="text-cyan-400 font-semibold">&lt; 2 sec</span>
                    </div>
                    <div className="flex items-center justify-between bg-gray-800 rounded-lg p-3">
                      <span className="text-gray-400">Reliability</span>
                      <span className="text-cyan-400 font-semibold">99.9%</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
