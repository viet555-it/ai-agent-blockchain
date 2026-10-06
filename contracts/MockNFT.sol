// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title MockNFT
 * @dev Simple ERC721 NFT for AI Agent minting demonstrations
 */
contract MockNFT {
    string public name = "Web3 AI Agent NFT";
    string public symbol = "AIAGENT";
    uint256 private _tokenIds;

    mapping(uint256 => address) private _owners;
    mapping(address => uint256) private _balances;
    mapping(uint256 => string) private _tokenURIs;

    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event NFTMinted(address indexed recipient, uint256 indexed tokenId, string tokenURI);

    function balanceOf(address owner) public view returns (uint256) {
        require(owner != address(0), "Address zero is not valid owner");
        return _balances[owner];
    }

    function ownerOf(uint256 tokenId) public view returns (address) {
        address owner = _owners[tokenId];
        require(owner != address(0), "Token does not exist");
        return owner;
    }

    function tokenURI(uint256 tokenId) public view returns (string memory) {
        require(_owners[tokenId] != address(0), "Token does not exist");
        return _tokenURIs[tokenId];
    }

    function mintNFT(address recipient, string memory uri) public returns (uint256) {
        _tokenIds++;
        uint256 newItemId = _tokenIds;

        _balances[recipient] += 1;
        _owners[newItemId] = recipient;
        _tokenURIs[newItemId] = uri;

        emit Transfer(address(0), recipient, newItemId);
        emit NFTMinted(recipient, newItemId, uri);

        return newItemId;
    }
}

