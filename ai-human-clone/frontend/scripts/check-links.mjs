// Checks that every internal link target in the source resolves to an app route.
//   node scripts/check-links.mjs
// Finds href="/…", href={`/…`}, href: "/…" (nav objects), router.push/replace("/…") and
// redirect("/…"). A `${…}` part may stand for one or more segments, so such a link only has
// to match the start of some route. Exit code 1 when a target matches no route.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const HOLE = "\u0000";

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.(tsx?|mjs)$/.test(name)) out.push(path);
  }
  return out;
}

const routes = walk(join(root, "app"))
  .filter((file) => /[\\/]page\.tsx$/.test(file))
  .map((file) => "/" + relative(join(root, "app"), file).split(sep).slice(0, -1).join("/"))
  .map((route) => route.replace(/\/\([^)]+\)/g, "") || "/");
const routeRegex = (route) => new RegExp("^" + route.replace(/\[[^\]]+\]/g, "[^/]+") + "/?$");
const patterns = routes.map((route) => ({ route, regex: routeRegex(route) }));

function resolves(target) {
  if (!target.includes(HOLE)) return patterns.some(({ regex }) => regex.test(target));
  if (patterns.some(({ regex }) => regex.test(target.replaceAll(HOLE, "x")))) return true;
  // Loose: the segments before the first `${…}` must start some route ([param] matches anything).
  const head = target.split(HOLE)[0].split("/").filter(Boolean);
  if (!target.split(HOLE)[0].endsWith("/")) head.pop(); // a segment that continues into `${…}`
  return routes.some((route) => {
    const parts = route.split("/").filter(Boolean);
    return head.length < parts.length && head.every((seg, i) => parts[i] === seg || /^\[.+\]$/.test(parts[i]));
  });
}

const found = /(?:href(?:=\{?|:)\s*["'`]|(?:push|replace|redirect)\(\s*["'`])(\/[^"'`\s?#]*)/g;
const problems = [];
let checked = 0;
for (const file of [...walk(join(root, "app")), ...walk(join(root, "components")), ...walk(join(root, "lib"))]) {
  readFileSync(file, "utf8").split("\n").forEach((line, index) => {
    for (const match of line.matchAll(found)) {
      const target = match[1].replace(/\$\{[^}]*\}/g, HOLE).replace(/\/+$/, "") || "/";
      if (target.startsWith("/api/") || /\.\w+$/.test(target)) continue; // API calls, static files
      checked += 1;
      if (!resolves(target)) problems.push(`${relative(root, file)}:${index + 1}  ${match[1]}`);
    }
  });
}
console.log(`${routes.length} routes, ${checked} internal link targets checked`);
if (problems.length) {
  console.log("No matching route:\n  " + problems.join("\n  "));
  process.exitCode = 1;
}
