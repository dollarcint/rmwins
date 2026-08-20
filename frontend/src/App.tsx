import { lazy, Suspense, type ComponentType } from 'react';
import LandingPage from './components/LandingPage';

const LoginPage = lazy(() => import('./components/LoginPage'));
const SurveyStatusPage = lazy(() => import('./components/SurveyStatusPage'));

function App() {
  const pathname = window.location.pathname.replace(/\/$/, '');
  let Page: ComponentType = LandingPage;

  if (pathname === '/login') {
    Page = LoginPage;
  } else if (pathname === '/survey') {
    Page = SurveyStatusPage;
  }

  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50" />}>
      <Page />
    </Suspense>
  );
}

export default App;
