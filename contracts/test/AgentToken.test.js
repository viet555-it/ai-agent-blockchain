const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("AgentToken Smart Contract", function () {
  let agentToken;
  let owner;
  let user1;
  let user2;

  const INITIAL_SUPPLY = 1_000_000n; // 1 million AGNT
  const DECIMALS = 18n;
  const ONE_TOKEN = 10n ** DECIMALS;

  beforeEach(async function () {
    [owner, user1, user2] = await ethers.getSigners();

    const AgentTokenFactory = await ethers.getContractFactory("AgentToken");
    agentToken = await AgentTokenFactory.deploy(owner.address, INITIAL_SUPPLY);
    await agentToken.waitForDeployment();
  });

  describe("1. Deployment & Basic Info", function () {
    it("Should set correct name and symbol", async function () {
      expect(await agentToken.name()).to.equal("Agent Token");
      expect(await agentToken.symbol()).to.equal("AGNT");
      expect(await agentToken.decimals()).to.equal(18);
    });

    it("Should assign initial supply to the owner", async function () {
      const ownerBalance = await agentToken.balanceOf(owner.address);
      const expectedSupply = INITIAL_SUPPLY * ONE_TOKEN;
      expect(ownerBalance).to.equal(expectedSupply);
      expect(await agentToken.totalSupply()).to.equal(expectedSupply);
    });

    it("Should set default maxTransferLimit to 500 AGNT", async function () {
      const defaultLimit = 500n * ONE_TOKEN;
      expect(await agentToken.maxTransferLimit()).to.equal(defaultLimit);
    });
  });

  describe("2. Faucet Functionality (For AI Agent Demo)", function () {
    it("Should allow user to claim tokens within faucet limit", async function () {
      const claimAmount = 50n * ONE_TOKEN;

      await expect(agentToken.connect(user1).faucet(claimAmount))
        .to.emit(agentToken, "FaucetClaimed")
        .withArgs(user1.address, claimAmount, (val) => val > 0n);

      expect(await agentToken.balanceOf(user1.address)).to.equal(claimAmount);
    });

    it("Should revert if faucet amount is zero", async function () {
      await expect(agentToken.connect(user1).faucet(0)).to.be.revertedWith(
        "AgentToken: Amount must be greater than 0"
      );
    });

    it("Should revert if faucet amount exceeds limit (100 AGNT)", async function () {
      const excessAmount = 101n * ONE_TOKEN;
      await expect(
        agentToken.connect(user1).faucet(excessAmount)
      ).to.be.revertedWith("AgentToken: Amount exceeds faucet limit");
    });

    it("Should revert if claiming again before cooldown expires", async function () {
      const claimAmount = 10n * ONE_TOKEN;
      await agentToken.connect(user1).faucet(claimAmount);

      await expect(
        agentToken.connect(user1).faucet(claimAmount)
      ).to.be.revertedWith("AgentToken: Faucet cooldown active");
    });

    it("Should allow claiming again after cooldown period passes", async function () {
      const claimAmount = 10n * ONE_TOKEN;
      await agentToken.connect(user1).faucet(claimAmount);

      // Advance time by 61 seconds (cooldown is 60 seconds)
      await time.increase(61);

      await expect(agentToken.connect(user1).faucet(claimAmount)).to.not.be.reverted;
      expect(await agentToken.balanceOf(user1.address)).to.equal(claimAmount * 2n);
    });
  });

  describe("3. Transfer & Guardrail Max Transfer Limit", function () {
    beforeEach(async function () {
      // Mint user1 600 AGNT for testing transfers
      await agentToken.connect(owner).mint(user1.address, 600n * ONE_TOKEN);
    });

    it("Should allow transfer within maxTransferLimit (<= 500 AGNT)", async function () {
      const transferAmount = 200n * ONE_TOKEN;
      await expect(
        agentToken.connect(user1).transfer(user2.address, transferAmount)
      ).to.changeTokenBalances(
        agentToken,
        [user1, user2],
        [-transferAmount, transferAmount]
      );
    });

    it("Should revert transfer if amount exceeds maxTransferLimit (> 500 AGNT)", async function () {
      const transferAmount = 501n * ONE_TOKEN;
      await expect(
        agentToken.connect(user1).transfer(user2.address, transferAmount)
      ).to.be.revertedWith("AgentToken: Transfer exceeds max limit");
    });

    it("Should revert if sender has insufficient balance", async function () {
      const excessiveAmount = 400n * ONE_TOKEN;
      // user2 currently has 0 tokens
      await expect(
        agentToken.connect(user2).transfer(user1.address, excessiveAmount)
      ).to.be.revertedWithCustomError(agentToken, "ERC20InsufficientBalance");
    });
  });

  describe("4. Guardrail Configuration & Admin Controls", function () {
    it("Should allow owner to update maxTransferLimit", async function () {
      const newLimit = 1000n * ONE_TOKEN;
      await expect(agentToken.connect(owner).setMaxTransferLimit(newLimit))
        .to.emit(agentToken, "MaxTransferLimitUpdated")
        .withArgs(500n * ONE_TOKEN, newLimit);

      expect(await agentToken.maxTransferLimit()).to.equal(newLimit);
    });

    it("Should revert if non-owner tries to update maxTransferLimit", async function () {
      const newLimit = 1000n * ONE_TOKEN;
      await expect(
        agentToken.connect(user1).setMaxTransferLimit(newLimit)
      ).to.be.revertedWithCustomError(agentToken, "OwnableUnauthorizedAccount");
    });

    it("Should allow owner to mint new tokens", async function () {
      const mintAmount = 500n * ONE_TOKEN;
      await expect(agentToken.connect(owner).mint(user1.address, mintAmount))
        .to.emit(agentToken, "TokensMinted")
        .withArgs(user1.address, mintAmount);

      expect(await agentToken.balanceOf(user1.address)).to.equal(mintAmount);
    });
  });

  describe("5. Dry-run Simulation Helper (validateTransfer for AI Agent)", function () {
    beforeEach(async function () {
      await agentToken.connect(owner).transfer(user1.address, 100n * ONE_TOKEN);
    });

    it("Should return true and Valid for compliant transfer parameters", async function () {
      const res = await agentToken.validateTransfer(
        user1.address,
        user2.address,
        50n * ONE_TOKEN
      );
      expect(res.isValid).to.be.true;
      expect(res.reason).to.equal("Valid");
    });

    it("Should return false when transfer amount exceeds limit", async function () {
      const res = await agentToken.validateTransfer(
        user1.address,
        user2.address,
        600n * ONE_TOKEN
      );
      expect(res.isValid).to.be.false;
      expect(res.reason).to.equal("Amount exceeds guardrail maxTransferLimit");
    });

    it("Should return false when sender has insufficient balance", async function () {
      const res = await agentToken.validateTransfer(
        user1.address,
        user2.address,
        200n * ONE_TOKEN
      );
      expect(res.isValid).to.be.false;
      expect(res.reason).to.equal("Insufficient balance");
    });

    it("Should return false when recipient is address zero", async function () {
      const res = await agentToken.validateTransfer(
        user1.address,
        ethers.ZeroAddress,
        10n * ONE_TOKEN
      );
      expect(res.isValid).to.be.false;
      expect(res.reason).to.equal("Invalid recipient address");
    });
  });
});
