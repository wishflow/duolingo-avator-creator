import { useEffect } from 'react';
import { legacyMarkup } from './legacy/legacyMarkup';

export function App() {
  useEffect(() => {
    let mounted = true;
    import('./legacy/avatarExplorer').catch((error) => {
      if (!mounted) return;
      console.error('Avatar editor failed to initialize:', error);
      document.getElementById('loadingOverlay')?.classList.add('hidden');
    });
    return () => {
      mounted = false;
    };
  }, []);

  return <div dangerouslySetInnerHTML={{ __html: legacyMarkup }} />;
}
