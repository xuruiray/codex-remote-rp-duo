export function diffBlock(text) {
  const pre = document.createElement("pre");
  pre.className = "diff";
  for (const line of text.replace(/\n$/, "").split("\n")) {
    const row = document.createElement("span");
    if (line.startsWith("+") && !line.startsWith("+++")) row.className = "added";
    if (line.startsWith("-") && !line.startsWith("---")) row.className = "removed";
    row.textContent = line || " ";
    pre.append(row);
  }
  return pre;
}
