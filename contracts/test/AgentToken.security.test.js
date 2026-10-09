const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

const ONE = 10n ** 18n;
describe("AgentToken security regressions", function () {
  let token, owner, spender, recipient;
  beforeEach(async function () {
    [owner, spender, recipient] = await ethers.getSigners();
    token = await (await ethers.getContractFactory("AgentToken")).deploy(owner.address, 1_000_000n);
    await token.waitForDeployment();
  });
  it("caps constructor minting and accepts deployment exactly at the cap", async function () {
    const factory = await ethers.getContractFactory("AgentToken");
    await expect(factory.deploy(owner.address, 10_000_001n)).to.be.revertedWithCustomError(token, "ERC20ExceededCap");
    const atCap = await factory.deploy(owner.address, 10_000_000n);
    expect(await atCap.totalSupply()).to.equal(await atCap.cap());
  });
  it("caps owner minting, including a one-unit overflow", async function () {
    await token.mint(owner.address, 9_000_000n * ONE);
    expect(await token.totalSupply()).to.equal(await token.MAX_TOTAL_SUPPLY());
    await expect(token.mint(owner.address, 1n)).to.be.revertedWithCustomError(token, "ERC20ExceededCap");
  });
  it("caps faucet and rolls cooldown back when mint fails", async function () {
    await token.mint(owner.address, 9_000_000n * ONE - ONE);
    await expect(token.connect(spender).faucet(2n * ONE)).to.be.revertedWithCustomError(token, "ERC20ExceededCap");
    expect(await token.lastFaucetClaim(spender.address)).to.equal(0n);
    await token.connect(spender).faucet(ONE);
    expect(await token.totalSupply()).to.equal(await token.cap());
    await expect(token.connect(recipient).faucet(1n)).to.be.revertedWithCustomError(token, "ERC20ExceededCap");
  });
  it("rejects mint by non-owner and mint to zero", async function () {
    await expect(token.connect(spender).mint(spender.address, ONE)).to.be.revertedWithCustomError(token, "OwnableUnauthorizedAccount");
    await expect(token.mint(ethers.ZeroAddress, ONE)).to.be.revertedWith("AgentToken: Cannot mint to zero address");
  });
  it("rejects a zero transfer limit", async function () {
    await expect(token.setMaxTransferLimit(0)).to.be.revertedWith("AgentToken: Limit must be greater than 0");
  });
  it("allows faucet exactly at 100 AGNT and at the cooldown boundary", async function () {
    await token.connect(spender).faucet(100n * ONE);
    const last = await token.lastFaucetClaim(spender.address);
    await time.setNextBlockTimestamp(last + 60n);
    await token.connect(spender).faucet(100n * ONE);
    expect(await token.balanceOf(spender.address)).to.equal(200n * ONE);
  });
  it("allows transfer exactly at the limit", async function () {
    await expect(token.transfer(recipient.address, 500n * ONE)).to.changeTokenBalances(token, [owner, recipient], [-500n * ONE, 500n * ONE]);
  });
  it("rejects transferFrom with insufficient allowance in validator and transaction", async function () {
    expect((await token.validateTransferFrom(owner.address, recipient.address, ONE, spender.address)).isValid).to.equal(false);
    await expect(token.connect(spender).transferFrom(owner.address, recipient.address, ONE)).to.be.revertedWithCustomError(token, "ERC20InsufficientAllowance");
  });
  it("checks self-spending allowance rather than exempting sender", async function () {
    expect((await token.validateTransferFrom(owner.address, recipient.address, ONE, owner.address)).isValid).to.equal(false);
    await expect(token.transferFrom(owner.address, recipient.address, ONE)).to.be.revertedWithCustomError(token, "ERC20InsufficientAllowance");
    await token.approve(owner.address, ONE);
    expect((await token.validateTransferFrom(owner.address, recipient.address, ONE, owner.address)).isValid).to.equal(true);
    await token.transferFrom(owner.address, recipient.address, ONE);
  });
  it("allows approved transferFrom and consumes allowance", async function () {
    await token.approve(spender.address, 500n * ONE);
    expect((await token.validateTransferFrom(owner.address, recipient.address, 500n * ONE, spender.address)).isValid).to.equal(true);
    await token.connect(spender).transferFrom(owner.address, recipient.address, 500n * ONE);
    expect(await token.allowance(owner.address, spender.address)).to.equal(0n);
    expect(await token.balanceOf(recipient.address)).to.equal(500n * ONE);
  });
  it("enforces transferFrom limit without consuming allowance on revert", async function () {
    await token.approve(spender.address, 600n * ONE);
    const result = await token.validateTransferFrom(owner.address, recipient.address, 501n * ONE, spender.address);
    expect(result.isValid).to.equal(false);
    expect(result.reason).to.equal("Amount exceeds guardrail maxTransferLimit");
    await expect(token.connect(spender).transferFrom(owner.address, recipient.address, 501n * ONE)).to.be.revertedWith("AgentToken: Transfer exceeds max limit");
    expect(await token.allowance(owner.address, spender.address)).to.equal(600n * ONE);
  });
  it("keeps unlimited allowance unchanged", async function () {
    await token.approve(spender.address, ethers.MaxUint256);
    await token.connect(spender).transferFrom(owner.address, recipient.address, ONE);
    expect(await token.allowance(owner.address, spender.address)).to.equal(ethers.MaxUint256);
  });
  it("rejects invalid sender, recipient and spender", async function () {
    expect((await token.validateTransfer(ethers.ZeroAddress, recipient.address, 0)).isValid).to.equal(false);
    expect((await token.validateTransferFrom(owner.address, ethers.ZeroAddress, ONE, spender.address)).isValid).to.equal(false);
    expect((await token.validateTransferFrom(owner.address, recipient.address, ONE, ethers.ZeroAddress)).isValid).to.equal(false);
  });
  it("matches ERC20 zero-transfer behavior, including transferFrom", async function () {
    expect((await token.validateTransfer(spender.address, recipient.address, 0)).isValid).to.equal(true);
    await expect(token.connect(spender).transfer(recipient.address, 0)).to.emit(token, "Transfer").withArgs(spender.address, recipient.address, 0);
    expect((await token.validateTransferFrom(owner.address, recipient.address, 0, spender.address)).isValid).to.equal(true);
    await expect(token.connect(spender).transferFrom(owner.address, recipient.address, 0)).not.to.be.reverted;
  });
});
