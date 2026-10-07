const { ethers, network } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  console.log("==================================================");
  console.log(`Starting deployment on network: ${network.name}`);
  console.log("==================================================");

  const [deployer] = await ethers.getSigners();
  console.log(`Deployer address: ${deployer.address}`);

  const balance = await ethers.provider.getBalance(deployer.address);
  console.log(`Deployer balance: ${ethers.formatEther(balance)} ETH`);

  const INITIAL_SUPPLY = 1_000_000n; // 1,000,000 AGNT

  console.log(`\nDeploying AgentToken contract with initial supply of ${INITIAL_SUPPLY} AGNT...`);
  const AgentTokenFactory = await ethers.getContractFactory("AgentToken");
  const agentToken = await AgentTokenFactory.deploy(deployer.address, INITIAL_SUPPLY);

  await agentToken.waitForDeployment();
  const contractAddress = await agentToken.getAddress();

  console.log(`>>> AgentToken deployed successfully at: ${contractAddress}`);

  // 1. Export ABI and Deployment Info for Python Backend & AI Agent
  const artifactPath = path.join(
    __dirname,
    "../artifacts/src/AgentToken.sol/AgentToken.json"
  );

  if (fs.existsSync(artifactPath)) {
    const artifact = JSON.parse(fs.readFileSync(artifactPath, "utf8"));
    const abi = artifact.abi;

    // Target directories to save artifacts for Python backend
    const exportDir = path.join(__dirname, "../exported");
    const backendAbiDir = path.join(__dirname, "../../backend/abi");

    [exportDir, backendAbiDir].forEach((dir) => {
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    });

    // Write ABI JSON
    fs.writeFileSync(
      path.join(exportDir, "AgentToken_abi.json"),
      JSON.stringify(abi, null, 2)
    );
    fs.writeFileSync(
      path.join(backendAbiDir, "AgentToken_abi.json"),
      JSON.stringify(abi, null, 2)
    );

    // Write Deployment Info
    const deploymentData = {
      network: network.name,
      contractAddress: contractAddress,
      deployer: deployer.address,
      deployedAt: new Date().toISOString(),
      initialSupply: INITIAL_SUPPLY.toString(),
    };

    fs.writeFileSync(
      path.join(exportDir, "deployment.json"),
      JSON.stringify(deploymentData, null, 2)
    );
    fs.writeFileSync(
      path.join(backendAbiDir, "deployment.json"),
      JSON.stringify(deploymentData, null, 2)
    );

    console.log(`\n[Exported] ABI and deployment info saved to:`);
    console.log(` - contracts/exported/`);
    console.log(` - backend/abi/`);
  }

  console.log("\nDeployment completed successfully!");
}

main().catch((error) => {
  console.error("Deployment failed:", error);
  process.exitCode = 1;
});
