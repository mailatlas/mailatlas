import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

export default defineConfig({
  site: "https://mailatlas.dev",
  integrations: [
    starlight({
      title: "MailAtlas",
      description: "Email ingestion for AI and data applications.",
      customCss: ["./src/styles/custom.css"],
      components: {
        ThemeProvider: "./src/components/DocsThemeProvider.astro",
        ThemeSelect: "./src/components/EmptyThemeSelect.astro",
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/chiragagrawal/mailatlas",
        },
      ],
      sidebar: [
        {
          label: "Start Here",
          items: [
            {
              label: "Overview",
              link: "/docs/",
            },
            "docs/getting-started/installation",
            "docs/getting-started/quickstart",
          ],
        },
        {
          label: "Concepts",
          items: [
            "docs/concepts/workspace-model",
            "docs/concepts/document-schema",
          ],
        },
        {
          label: "Interfaces",
          items: [
            "docs/cli/overview",
            "docs/python/overview",
            "docs/config/parser-cleaning",
          ],
        },
        {
          label: "Examples",
          items: [
            "docs/examples/eml-ingest",
            "docs/examples/mbox-ingest",
          ],
        },
        {
          label: "Background",
          items: [
            "docs/marketing/why-not-connectors",
            "docs/marketing/security-and-privacy",
            "docs/marketing/roadmap",
          ],
        },
      ],
    }),
  ],
});
