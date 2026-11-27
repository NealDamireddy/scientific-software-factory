import { fileURLToPath } from "node:url";

export default {
  devIndicators: false,
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
};
