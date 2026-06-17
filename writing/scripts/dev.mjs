import { spawn } from "node:child_process";

const processes = [
  ["server", "npm", ["run", "server"]],
  ["client", "npm", ["run", "client"]]
];

for (const [name, command, args] of processes) {
  const child = spawn(command, args, {
    stdio: "inherit",
    shell: process.platform === "win32"
  });

  child.on("exit", (code) => {
    if (code && code !== 0) {
      console.error(`${name} exited with code ${code}`);
      process.exit(code);
    }
  });
}

process.on("SIGINT", () => process.exit(0));
