// Regenerates the web UI screenshots used by the documentation.
//
//   1. Start the server:   dotnet run --project CodesysMcpServer.Web --launch-profile CodesysMcpServer
//   2. From docs/:         npm run screenshots
//
// The page itself (HTML, CSS, version badge, Swagger UI) comes from the running server.
// The CODESYS-dependent API responses (settings, profiles, session, structure, file
// browser) are replaced with the sample data below, so the screenshots look the same on any
// machine — with or without CODESYS installed. Set BASE_URL to use another address and
// CHROMIUM_PATH to use a specific Chromium binary.
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const BASE_URL = process.env.BASE_URL ?? 'http://127.0.0.1:5088';
const OUT_DIR = fileURLToPath(new URL('../src/assets/screenshots/', import.meta.url));

const EXE = 'C:\\Program Files\\CODESYS 3.5.21.30\\CODESYS\\Common\\CODESYS.exe';
const PROJECT_DIR = 'C:\\Projects\\Conveyor';
const PROJECT = `${PROJECT_DIR}\\Conveyor.project`;

const minutesAgo = (m) => new Date(Date.now() - m * 60_000).toISOString();

const settings = {
  executablePath: EXE,
  projectPath: PROJECT,
  profile: 'CODESYS V3.5 SP21 Patch 3',
  executableExists: true,
  projectExists: true,
};

const profiles = [
  { name: 'CODESYS V3.5 SP20 Patch 0' },
  { name: 'CODESYS V3.5 SP21 Patch 3' },
];

const sessionStates = {
  ready: {
    enabled: true, state: 'ready', processId: 11872, startedAt: minutesAgo(42),
    busySince: null, currentScript: null, requestsServed: 37, lastError: null,
  },
  busy: {
    enabled: true, state: 'busy', processId: 11872, startedAt: minutesAgo(43),
    busySince: new Date(Date.now() - 4_000).toISOString(), currentScript: 'compile.py',
    requestsServed: 37, lastError: null,
  },
  stopped: {
    enabled: true, state: 'stopped', processId: null, startedAt: null,
    busySince: null, currentScript: null, requestsServed: 0, lastError: null,
  },
};

const pou = (path, type, language) => ({ name: path.split('/').pop(), path, type, language });
const structure = {
  projectPath: PROJECT,
  applications: ['Device/PLC Logic/Application'],
  folders: [
    'Device/PLC Logic/Application/Conveyor',
    'Device/PLC Logic/Application/Types',
  ],
  pous: [
    pou('Device/PLC Logic/Application/PLC_PRG', 'PRG', 'ST'),
    pou('Device/PLC Logic/Application/Conveyor/FB_Conveyor', 'FB', 'ST'),
    pou('Device/PLC Logic/Application/Conveyor/FB_Motor', 'FB', 'ST'),
    pou('Device/PLC Logic/Application/Conveyor/FC_Scale', 'FUN', 'ST'),
    pou('Device/PLC Logic/Application/Conveyor/SFC_Sequence', 'PRG', 'SFC'),
  ],
  gvls: [
    { name: 'GVL_IO', path: 'Device/PLC Logic/Application/GVL_IO', variableCount: 24 },
    { name: 'GVL_Params', path: 'Device/PLC Logic/Application/GVL_Params', variableCount: 9 },
  ],
  duts: [
    { name: 'ST_MotorData', path: 'Device/PLC Logic/Application/Types/ST_MotorData', kind: 'STRUCT' },
  ],
  enums: [
    { name: 'E_ConveyorState', path: 'Device/PLC Logic/Application/Types/E_ConveyorState', valueCount: 5 },
  ],
  counts: { pous: 5, gvls: 2, duts: 1, enums: 1 },
};

const listing = {
  path: PROJECT_DIR,
  parent: 'C:\\Projects',
  entries: [
    { name: 'Backup', fullPath: `${PROJECT_DIR}\\Backup`, isDirectory: true },
    { name: 'Libraries', fullPath: `${PROJECT_DIR}\\Libraries`, isDirectory: true },
    { name: 'Conveyor.project', fullPath: PROJECT, isDirectory: false },
    { name: 'Conveyor_Test.project', fullPath: `${PROJECT_DIR}\\Conveyor_Test.project`, isDirectory: false },
  ],
};

async function newPage(browser, sessionState = 'ready', colorScheme = 'light') {
  const page = await browser.newPage({ viewport: { width: 900, height: 900 }, deviceScaleFactor: 2, colorScheme });
  const json = (route, body) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/settings', (r) => json(r, settings));
  await page.route('**/profiles?*', (r) => json(r, profiles));
  await page.route('**/session', (r) => json(r, sessionStates[sessionState]));
  await page.route('**/structure', (r) => json(r, structure));
  await page.route('**/files?*', (r) => json(r, listing));
  await page.goto(BASE_URL + '/');
  await page.waitForSelector('#app-version:not(:empty)');
  await page.waitForSelector('#profile-status.ok');
  await page.waitForSelector('#session-dot.' + sessionState);
  return page;
}

const shot = (target, name) => target.screenshot({ path: OUT_DIR + name, animations: 'disabled' });

const executablePath = process.env.CHROMIUM_PATH
  ?? (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);
const browser = await chromium.launch({ executablePath });
await mkdir(OUT_DIR, { recursive: true });

try {
  let page = await newPage(browser);
  await shot(page.locator('main'), 'settings-page.png');
  await shot(page.locator('h1'), 'version-badge.png');

  await page.click('#structure-button');
  await page.waitForSelector('#structure-status.ok');
  await shot(page.locator('main'), 'project-structure.png');

  await page.click('.browse-btn[data-target=projectPath]');
  await page.waitForSelector('.modal-entry');
  await page.mouse.move(0, 0);
  await shot(page.locator('.modal'), 'file-browser.png');
  await page.close();

  page = await newPage(browser, 'ready', 'dark');
  await shot(page.locator('main'), 'settings-page-dark.png');
  await page.close();

  for (const state of ['stopped', 'busy']) {
    page = await newPage(browser, state);
    await shot(page.locator('#session-card'), `session-${state}.png`);
    await page.close();
  }
  page = await newPage(browser, 'ready');
  await shot(page.locator('#session-card'), 'session-ready.png');
  await page.close();

  page = await browser.newPage({ viewport: { width: 1200, height: 1000 }, deviceScaleFactor: 2 });
  await page.goto(BASE_URL + '/swagger/index.html');
  await page.waitForSelector('.opblock');
  await shot(page, 'swagger.png');
  await page.close();
} finally {
  await browser.close();
}

console.log(`Screenshots written to ${OUT_DIR}`);
