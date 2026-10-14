const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../../core/templates/core/base.html'), 'utf8');
const setup = template.slice(template.indexOf('const adminLoadedScripts='), template.indexOf('function showAdminAjaxProgress()'));
const loader = template.match(/function adminLoadStylesheet\([\s\S]*?\n}\n/)[0];

function stylesheetRuntime() {
  class Link {
    constructor(href) {
      this.href = href;
      this.rel = 'stylesheet';
      this.parentElement = null;
      this.sheet = null;
      this.attributes = new Map();
      this.listeners = new Map();
    }
    addEventListener(name, listener) { this.listeners.set(name, listener); }
    hasAttribute(name) { return this.attributes.has(name); }
    getAttribute(name) { return this.attributes.get(name); }
    setAttribute(name, value) { this.attributes.set(name, value); }
    remove() {
      if (this.parentElement) {
        this.parentElement.links = this.parentElement.links.filter(link => link !== this);
        this.parentElement = null;
      }
    }
    load() { this.sheet = {}; this.listeners.get('load')?.(); }
    fail() { this.listeners.get('error')?.(); }
  }
  function container() {
    return {
      links: [],
      appendChild(link) {
        link.remove();
        this.links.push(link);
        link.parentElement = this;
      },
      querySelectorAll() { return this.links; },
    };
  }
  const head = container();
  const main = container();
  const leaflet = new Link('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
  leaflet.sheet = {};
  main.appendChild(leaflet);
  const document = {
    head,
    scripts: [],
    querySelectorAll(selector) {
      return selector.startsWith('#admin-main-content') ? [...main.links] : [...head.links, ...main.links];
    },
    createElement() { return new Link(''); },
  };
  const context = vm.createContext({document, window: {location: {href: 'http://localhost/machines/'}}, URL});
  vm.runInContext(`${setup}\n${loader}`, context);
  return {head, main, leaflet, Link, load: context.adminLoadStylesheet};
}

test('Leaflet styles survive leaving and returning to a page loaded directly', async () => {
  const runtime = stylesheetRuntime();
  // AJAX navigation discards all nodes left in the main content.
  [...runtime.main.links].forEach(link => link.remove());
  await runtime.load(runtime.leaflet.href);
  assert.equal(runtime.leaflet.parentElement, runtime.head);
  assert.equal(runtime.head.links.filter(link => link.href === runtime.leaflet.href).length, 1);
  assert.ok(runtime.leaflet.sheet);
});

test('concurrent loads share one link and retain integrity attributes', async () => {
  const runtime = stylesheetRuntime();
  const source = new runtime.Link('/static/map.css');
  source.setAttribute('integrity', 'sha256-test');
  source.setAttribute('crossorigin', '');
  const first = runtime.load('/static/map.css', source);
  const second = runtime.load('/static/map.css', source);
  assert.equal(first, second);
  const links = runtime.head.links.filter(link => link.href === 'http://localhost/static/map.css');
  assert.equal(links.length, 1);
  assert.equal(links[0].getAttribute('integrity'), 'sha256-test');
  assert.equal(links[0].getAttribute('crossorigin'), '');
  links[0].load();
  await Promise.all([first, second]);
});

test('a failed stylesheet request can be retried on the next navigation', async () => {
  const runtime = stylesheetRuntime();
  const first = runtime.load('/static/retry.css');
  const failed = runtime.head.links.find(link => link.href.endsWith('/retry.css'));
  failed.fail();
  await assert.rejects(first, /โหลดรูปแบบหน้าไม่สำเร็จ/);
  assert.equal(failed.parentElement, null);
  const retry = runtime.load('/static/retry.css');
  const replacement = runtime.head.links.find(link => link.href.endsWith('/retry.css'));
  assert.notEqual(replacement, failed);
  replacement.load();
  await retry;
});
