// Read-only by default. NEW_OWNER is a public address, never a private key.
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const nextOwner = process.env.NEW_OWNER;
  if (!nextOwner || !ethers.isAddress(nextOwner) || nextOwner === ethers.ZeroAddress) {
    throw new Error("Set NEW_OWNER to the public address of your replacement wallet");
  }
  const { chainId } = await ethers.provider.getNetwork();
  const manifestPath = path.join(__dirname, "../../backend/abi", String(chainId), "deployment.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (String(manifest.chainId) !== String(chainId)) throw new Error("Deployment chain mismatch");
  if (await ethers.provider.getCode(manifest.contractAddress) === "0x") throw new Error("No contract on this chain");
  const [signer] = await ethers.getSigners();
  if (!signer) throw new Error("No current owner signer configured");
  // Minimal ABI also works with the previously deployed version.
  const token = new ethers.Contract(manifest.contractAddress, [
    "function owner() view returns (address)", "function transferOwnership(address newOwner)",
  ], signer);
  const currentOwner = await token.owner();
  if (currentOwner.toLowerCase() !== signer.address.toLowerCase()) throw new Error("Configured signer is not the current owner");
  if (currentOwner.toLowerCase() === nextOwner.toLowerCase()) throw new Error("Replacement owner must be a different wallet");
  await token.transferOwnership.staticCall(nextOwner);
  console.log(`Chain ${chainId}; contract ${manifest.contractAddress}; owner ${currentOwner}; proposed owner ${nextOwner}`);
  if (process.env.SEND_OWNERSHIP_TRANSFER !== "true") {
    console.log("Simulation passed. No transaction sent. Set SEND_OWNERSHIP_TRANSFER=true only after checking the replacement address.");
    return;
  }
  const tx = await token.transferOwnership(nextOwner);
  await tx.wait();
  console.log(`Ownership changed to ${await token.owner()}; transaction ${tx.hash}`);
}
main().catch((error) => { console.error(error.message); process.exitCode = 1; });
