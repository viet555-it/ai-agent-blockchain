// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Capped.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title AgentToken
 * @dev ERC-20 Token designed for AI Agent interaction and guardrail demonstrations.
 * Includes faucet capabilities and guardrail-friendly limit checks.
 */
contract AgentToken is ERC20Capped, Ownable {
    // Applied centrally to constructor, owner mint and faucet mint.
    uint256 public constant MAX_TOTAL_SUPPLY = 10_000_000 * 10 ** 18;
    // Maximum amount allowed per faucet claim (e.g., 100 AGNT)
    uint256 public constant FAUCET_AMOUNT_LIMIT = 100 * 10 ** 18;

    // Safety guardrail: maximum amount per transfer (default 500 AGNT)
    uint256 public maxTransferLimit;

    // Cooldown tracking for faucet claims: user address => last claim timestamp
    mapping(address => uint256) public lastFaucetClaim;
    uint256 public faucetCooldown = 1 minutes;

    // Events for agent and backend indexing
    event FaucetClaimed(address indexed recipient, uint256 amount, uint256 timestamp);
    event MaxTransferLimitUpdated(uint256 oldLimit, uint256 newLimit);
    event TokensMinted(address indexed to, uint256 amount);

    /**
     * @param initialOwner Address of the contract owner (deployer)
     * @param initialSupply Initial supply minted to owner (in ether units, e.g. 1,000,000)
     */
    constructor(address initialOwner, uint256 initialSupply)
        ERC20("Agent Token", "AGNT")
        ERC20Capped(MAX_TOTAL_SUPPLY)
        Ownable(initialOwner)
    {
        maxTransferLimit = 500 * 10 ** 18; // Default 500 AGNT limit
        _mint(initialOwner, initialSupply * 10 ** decimals());
    }

    /**
     * @notice Allows users or the AI Agent to request test tokens
     * @param amount The requested amount in wei (must be <= FAUCET_AMOUNT_LIMIT)
     */
    function faucet(uint256 amount) external {
        require(amount > 0, "AgentToken: Amount must be greater than 0");
        require(amount <= FAUCET_AMOUNT_LIMIT, "AgentToken: Amount exceeds faucet limit");
        require(
            block.timestamp >= lastFaucetClaim[msg.sender] + faucetCooldown,
            "AgentToken: Faucet cooldown active"
        );

        lastFaucetClaim[msg.sender] = block.timestamp;
        _mint(msg.sender, amount);
        emit FaucetClaimed(msg.sender, amount, block.timestamp);
    }

    /**
     * @notice Owner can mint new tokens
     */
    function mint(address to, uint256 amount) external onlyOwner {
        require(to != address(0), "AgentToken: Cannot mint to zero address");
        _mint(to, amount);
        emit TokensMinted(to, amount);
    }

    /**
     * @notice Updates the maximum transfer limit (Guardrail configuration)
     */
    function setMaxTransferLimit(uint256 newLimit) external onlyOwner {
        require(newLimit > 0, "AgentToken: Limit must be greater than 0");
        uint256 oldLimit = maxTransferLimit;
        maxTransferLimit = newLimit;
        emit MaxTransferLimitUpdated(oldLimit, newLimit);
    }

    /**
     * @notice Helper function for AI Agent / Guardrail to simulate and validate transfer before sending
     * @dev Does not modify state, callable off-chain by Agent Read Tools (eth_call)
     */
    function validateTransfer(
        address sender,
        address recipient,
        uint256 amount
    ) public view returns (bool isValid, string memory reason) {
        if (sender == address(0)) {
            return (false, "Invalid sender address");
        }
        if (recipient == address(0)) {
            return (false, "Invalid recipient address");
        }
        if (amount > maxTransferLimit) {
            return (false, "Amount exceeds guardrail maxTransferLimit");
        }
        if (balanceOf(sender) < amount) {
            return (false, "Insufficient balance");
        }
        return (true, "Valid");
    }

    /**
     * @notice Validate transferFrom, including self-spending allowance.
     * @dev spender is the caller of transferFrom, not the recipient.
     */
    function validateTransferFrom(
        address sender,
        address recipient,
        uint256 amount,
        address spender
    ) external view returns (bool isValid, string memory reason) {
        if (spender == address(0)) {
            return (false, "Invalid spender address");
        }
        (isValid, reason) = validateTransfer(sender, recipient, amount);
        if (!isValid) return (isValid, reason);
        if (allowance(sender, spender) < amount) {
            return (false, "Insufficient allowance for spender");
        }
        return (true, "Valid");
    }

    /**
     * @notice Override transfer to enforce maxTransferLimit guardrail
     */
    function transfer(address to, uint256 value) public override returns (bool) {
        require(value <= maxTransferLimit, "AgentToken: Transfer exceeds max limit");
        return super.transfer(to, value);
    }

    /**
     * @notice Override transferFrom to enforce maxTransferLimit guardrail
     */
    function transferFrom(address from, address to, uint256 value) public override returns (bool) {
        require(value <= maxTransferLimit, "AgentToken: Transfer exceeds max limit");
        return super.transferFrom(from, to, value);
    }
}
