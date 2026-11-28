import { fileURLToPath } from "node:url";

export default {
  ...(process.env.LABFACTORY_STATIC_WORKSPACE === "1" ? { output: "export", distDir: ".next/research-export", assetPrefix: "/research" } : {}),
  webpack(config) {
    config.module.rules.push({ test: /index\.html$/, resourceQuery: /reviewer-template/, type: "asset/source" });
    return config;
  },
  ...(process.env.LABFACTORY_API_ORIGIN && process.env.LABFACTORY_STATIC_WORKSPACE !== "1" ? {
    async rewrites() {
      const upstream = new URL(process.env.LABFACTORY_API_ORIGIN).origin;
      return { fallback: ["/api/:path*", "/examples/tabular/:path*", "/evolve/:path*", "/style.css", "/mcp"].map(
        source => ({ source, destination: upstream + source })) };
    },
  } : {}),
  devIndicators: false,
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
};
