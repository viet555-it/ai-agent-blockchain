const { expect } = require("chai");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { exportDeployment } = require("../scripts/deploy");

describe("Chain-scoped deployment exports", function () {
  let root;
  beforeEach(function () { root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-deployment-test-")); });
  afterEach(function () {
    // Remove only known test files/directories; never recursively remove a computed path.
    for (const parent of ["contracts/exported", "backend/abi"]) {
      for (const chain of ["11155111", "31337"]) {
        const dir = path.join(root, parent, chain);
        for (const name of ["AgentToken_abi.json", "deployment.json"]) {
          const file = path.join(dir, name); if (fs.existsSync(file)) fs.unlinkSync(file);
        }
        if (fs.existsSync(dir)) fs.rmdirSync(dir);
      }
      const dir = path.join(root, parent); if (fs.existsSync(dir)) fs.rmdirSync(dir);
    }
    for (const parent of ["contracts", "backend"]) {
      const dir = path.join(root, parent); if (fs.existsSync(dir)) fs.rmdirSync(dir);
    }
    fs.rmdirSync(root);
  });
  it("does not change Sepolia deployment/ABI when local artifacts are exported", function () {
    exportDeployment(root, [{ name: "old" }], { chainId: "11155111", network: "sepolia", contractAddress: "old" });
    const before = ["contracts/exported", "backend/abi"].map(parent => ["deployment.json", "AgentToken_abi.json"].map(name => fs.readFileSync(path.join(root, parent, "11155111", name), "utf8")));
    exportDeployment(root, [{ name: "new" }], { chainId: "31337", network: "hardhat", contractAddress: "new" });
    for (const [i, parent] of ["contracts/exported", "backend/abi"].entries()) {
      for (const [j, name] of ["deployment.json", "AgentToken_abi.json"].entries()) expect(fs.readFileSync(path.join(root, parent, "11155111", name), "utf8")).to.equal(before[i][j]);
      expect(JSON.parse(fs.readFileSync(path.join(root, parent, "31337/deployment.json"))).contractAddress).to.equal("new");
      expect(fs.existsSync(path.join(root, parent, "deployment.json"))).to.equal(false);
    }
  });
  it("rejects a chainId that can escape the export directory", function () {
    expect(() => exportDeployment(root, [], { chainId: "../11155111" })).to.throw("Invalid deployment chainId");
  });
});
