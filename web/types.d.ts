// Browser facts the DOM typings leave out, for the type check only (npm run typecheck); nothing here is loaded.
interface Window {
  L?: any;                                       // Leaflet, loaded on demand by the anchor page (vendor/leaflet)
  webkitAudioContext?: typeof AudioContext;      // older Safari
}
interface Navigator { standalone?: boolean }     // Safari: opened from the home screen
interface Element {
  dataset: DOMStringMap;                         // every element the pages touch is an HTML or SVG element
  setAttribute(name: string, value: string | number | boolean): void;   // the browser stringifies the value
}
// Event handlers here are only attached to elements, so the target is one.
interface EventTarget { closest(selectors: string): HTMLElement | null }
