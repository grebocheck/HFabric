import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";

const schemaUrl = new URL("../openapi.json", import.meta.url);
const generated = COMMENT_HEADER + astToString(await openapiTS(schemaUrl, { silent: true }));
const expected = readFileSync(resolve("src/types.generated.ts"), "utf8");

if (expected !== generated) {
  console.error("src/types.generated.ts is stale; run npm run openapi:generate");
  process.exit(1);
}
