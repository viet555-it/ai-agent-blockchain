const { ethers, network, artifacts } = require("hardhat");
const fs = require("fs");
const path = require("path");

function exportDeployment(baseDir, abi, deployment) {
  const chainId = String(deployment.chainId);
  if (!/^[1-9][0-9]*$/.test(chainId)) throw new Error("Invalid deployment chainId");
  for (const parent of ["contracts/exported", "backend/abi"]) {
    const dir = path.join(baseDir, parent, chainId);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "AgentToken_abi.json"), JSON.stringify(abi, null, 2) + "\n");
    fs.writeFileSync(path.join(dir, "deployment.json"), JSON.stringify(deployment, null, 2) + "\n");
  }
}

async function main() {
  const [deployer] = await ethers.getSigners();
  if (!deployer) throw new Error("No deployment signer configured");
  const { chainId } = await ethers.provider.getNetwork();
  const initialSupply = 1_000_000n;
  const factory = await ethers.getContractFactory("AgentToken");
  // Resolve the artifact before sending a transaction so export cannot silently skip it.
  const artifact = await artifacts.readArtifact("AgentToken");
  const request = await factory.getDeployTransaction(deployer.address, initialSupply);
  const gas = await ethers.provider.estimateGas({ ...request, from: deployer.address });
  const fees = await ethers.provider.getFeeData();
  const gasPrice = fees.maxFeePerGas ?? fees.gasPrice;
  if (gasPrice === null) throw new Error("Unable to estimate deployment gas price");
  const gasLimit = (gas * 120n + 99n) / 100n;
  const required = gasLimit * gasPrice;
  const balance = await ethers.provider.getBalance(deployer.address);
  if (balance < required) throw new Error(`Insufficient deployment balance; estimated requirement ${ethers.formatEther(required)} ETH`);
  console.log(`Deploying on ${network.name} (chain ${chainId}), owner ${deployer.address}`);
  const token = await factory.deploy(deployer.address, initialSupply, {
    gasLimit,
    ...(fees.maxFeePerGas !== null ? { maxFeePerGas: gasPrice, maxPriorityFeePerGas: fees.maxPriorityFeePerGas ?? 0n } : { gasPrice }),
  });
  await token.waitForDeployment();
  const address = await token.getAddress();
  const code = await ethers.provider.getCode(address);
  exportDeployment(path.resolve(__dirname, "../.."), artifact.abi, {
    network: network.name, chainId: chainId.toString(), contractAddress: address,
    deployer: deployer.address, deployedAt: new Date().toISOString(),
    initialSupply: initialSupply.toString(), runtimeCodeHash: ethers.keccak256(code),
    transactionHash: token.deploymentTransaction().hash,
  });
  console.log(`Deployed ${address}; artifacts exported under chain ${chainId}`);
  if (network.name === "hardhat") console.log("This in-process chain ends when the command exits. Use localhost for a persistent backend demo.");
}

module.exports = { exportDeployment, main };
if (require.main === module) main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
