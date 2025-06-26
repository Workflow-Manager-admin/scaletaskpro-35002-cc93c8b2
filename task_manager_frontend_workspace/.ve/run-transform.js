const fs = require('fs');
const path = require('path');
const jscodeshift = require('jscodeshift');
const diff = require('diff'); // Make sure you install: npm install diff
const transformer = require('./transform');

async function main() {
  const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
  const { file, line, changes } = input;

  const filePath = path.resolve(file);
  const originalCode = fs.readFileSync(filePath, 'utf-8');

  const transformedCode = transformer(
    { source: originalCode, path: filePath },
    { jscodeshift, changes, line: parseInt(line, 10) }
  );

  if (originalCode === transformedCode) {
    console.log(`No changes detected for ${filePath}`);
    process.exit(0);
  }

  // Use diff library to detect changed sections
  const changeset = diff.diffLines(originalCode, transformedCode);

  const editBlocks = [];
  let currentSearch = '';
  let currentReplace = '';

  changeset.forEach(part => {
    if (part.added) {
      currentReplace += part.value;
    } else if (part.removed) {
      currentSearch += part.value;
    } else {
      // Unchanged section → if we have accumulated edits, push as block
      if (currentSearch.trim() !== '' || currentReplace.trim() !== '') {
        editBlocks.push({
          searchText: currentSearch.trim(),
          replaceText: currentReplace.trim(),
        });
        currentSearch = '';
        currentReplace = '';
      }
    }
  });

  // Handle trailing edits
  if (currentSearch.trim() !== '' || currentReplace.trim() !== '') {
    editBlocks.push({
      searchText: currentSearch.trim(),
      replaceText: currentReplace.trim(),
    });
  }

  if (editBlocks.length > 0) {
    let combinedBlock = `<<<EDIT_BLOCK_START>>>\n`;

    editBlocks.forEach((block, index) => {
      const subBlock = `
${filePath}
<<<<<<< SEARCH
${block.searchText}
=======
${block.replaceText}
>>>>>>> REPLACE
      `.trim();

      combinedBlock += `\n${subBlock}\n`;
    });

    combinedBlock += `<<<EDIT_BLOCK_END>>>`;

    console.log(combinedBlock);
  } else {
    console.log(`No meaningful edits detected for ${filePath}`);
  }
}

main().catch(err => {
  console.error(`Transform error: ${err.message}`);
  process.exit(1);
});
