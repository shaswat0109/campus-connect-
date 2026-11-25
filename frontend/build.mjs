import { readFile, mkdir, writeFile } from "node:fs/promises";

const read = (name) => readFile(new URL(name, import.meta.url), "utf8");
const [template, css, js] = await Promise.all([
  read("index.html"), read("styles.css"), read("campus.js"),
]);
const html = template
  .replace("{{ campus_css | safe }}", () => css)
  .replace("{{ campus_js | safe }}", () => js)
  .replace('href="/campus"', 'href="/"');

if (html.includes("{{ campus_") || !html.includes("<style>") || !html.includes("<script>")) {
  throw new Error("Campus frontend assets could not be embedded.");
}

await mkdir(new URL("dist/", import.meta.url), { recursive: true });
await writeFile(new URL("dist/index.html", import.meta.url), html, "utf8");
