export default {
  output: "export",
  poweredByHeader: false,
  trailingSlash: true,
  env: { NEXT_PUBLIC_FIXTURE_PREVIEW: process.env.VERCEL_ENV === "preview" ? "1" : "0" },
};
