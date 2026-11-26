export default {
  output: "export",
  trailingSlash: true,
  poweredByHeader: false,
  // The repo root has its own lockfile. Pin the root so Next resolves from this package.
  turbopack: { root: import.meta.dirname },
};
