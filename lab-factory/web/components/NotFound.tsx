"use client";

import { routeHref } from "../lib/route.ts";

export function NotFound() {
  return (
    <div className="page not-found">
      <h1>That project or experiment doesn&apos;t exist in this lab.</h1>
      <p>
        <a className="text-link" href={routeHref({ view: "home" })}>Go to lab home</a>
      </p>
    </div>
  );
}
