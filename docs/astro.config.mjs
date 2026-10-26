// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Published to GitHub Pages by .github/workflows/docs.yml.
export default defineConfig({
  site: 'https://bartk1990.github.io',
  base: '/CodesysMcpNet',
  integrations: [
    starlight({
      title: 'CODESYS MCP Server',
      description: 'Drive a CODESYS V3 project from AI assistants and scripts via MCP and REST.',
      favicon: '/favicon.ico',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/BartK1990/CodesysMcpNet' },
      ],
      editLink: {
        baseUrl: 'https://github.com/BartK1990/CodesysMcpNet/edit/master/docs/',
      },
      sidebar: [
        { label: 'Home', link: '/' },
        {
          label: 'Getting started',
          items: [
            'getting-started/introduction',
            'getting-started/installation',
            'getting-started/first-run',
          ],
        },
        {
          label: 'Guides',
          items: [
            'guides/settings-page',
            'guides/mcp-clients',
            'guides/rest-api',
            'guides/persistent-session',
            'guides/multiple-projects',
            'guides/windows-service',
          ],
        },
        {
          label: 'Reference',
          items: ['reference/mcp-tools', 'reference/configuration', 'reference/troubleshooting'],
        },
        {
          label: 'Development',
          items: ['development/building', 'development/releasing'],
        },
      ],
    }),
  ],
});
