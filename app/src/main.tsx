import { render } from 'preact';
import { registerSW } from 'virtual:pwa-register';
import { App } from './App';
import { init } from './store';
import './styles.css';

render(<App />, document.getElementById('app')!);
init();
registerSW({ immediate: true });
