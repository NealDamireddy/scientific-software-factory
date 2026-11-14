export default {
  output: "export",
  poweredByHeader: false,
  trailingSlash: true,
  env: {
    NEXT_PUBLIC_FIXTURE_PREVIEW: process.env.VERCEL_ENV === "preview" ? "1" : "0",
    NEXT_PUBLIC_PREVIEW_COMMIT: process.env.VERCEL_ENV === "preview" ? process.env.VERCEL_GIT_COMMIT_SHA || "" : "",
  },
};
