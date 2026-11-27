const basePath = process.env.EVOLVE_BASE_PATH || "";

export default {
  basePath,
  // Keep the standalone export available when building the combined reviewer portal.
  distDir: basePath === "/evolve" ? ".next/evolve-export" : ".next",
  output: "export",
  poweredByHeader: false,
  trailingSlash: true,
  env: {
    NEXT_PUBLIC_EVOLVE_BASE_PATH: basePath,
    NEXT_PUBLIC_FIXTURE_PREVIEW: process.env.VERCEL_ENV === "preview" ? "1" : "0",
    NEXT_PUBLIC_PREVIEW_COMMIT: process.env.VERCEL_ENV === "preview" ? process.env.VERCEL_GIT_COMMIT_SHA || "" : "",
  },
};
