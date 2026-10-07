const { createCanvas, loadImage } = require('./app_source/node_modules/@napi-rs/canvas');
const fs = require('fs');

async function processImage() {
    const img = await loadImage('d:\\Ai Studio Pro\\phoenix_logo.png_2K_20261007052259.jpg');
    const width = img.width;
    const height = img.height;
    
    const canvas = createCanvas(width, height);
    const ctx = canvas.getContext('2d');
    
    // Set up rounded rectangle clipping
    const cornerRadius = width * 0.2; // 20% corner radius
    ctx.beginPath();
    ctx.moveTo(cornerRadius, 0);
    ctx.lineTo(width - cornerRadius, 0);
    ctx.quadraticCurveTo(width, 0, width, cornerRadius);
    ctx.lineTo(width, height - cornerRadius);
    ctx.quadraticCurveTo(width, height, width - cornerRadius, height);
    ctx.lineTo(cornerRadius, height);
    ctx.quadraticCurveTo(0, height, 0, height - cornerRadius);
    ctx.lineTo(0, cornerRadius);
    ctx.quadraticCurveTo(0, 0, cornerRadius, 0);
    ctx.closePath();
    ctx.clip();
    
    // Draw image inside the clipped area
    ctx.drawImage(img, 0, 0, width, height);
    
    // Save to transparent PNG
    const buffer = canvas.toBuffer('image/png');
    fs.writeFileSync('d:\\Ai Studio Pro\\phoenix_transparent.png', buffer);
    console.log('Saved transparent PNG to phoenix_transparent.png');
}

processImage().catch(console.error);
