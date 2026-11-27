const basePath = process.env.NEXT_PUBLIC_EVOLVE_BASE_PATH || "";

export const inLabFactory = basePath === "/evolve";

export function evolvePath(path: string) {
  return basePath + path;
}
