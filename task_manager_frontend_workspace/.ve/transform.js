module.exports = function transformer(fileInfo, { jscodeshift: j, changes, line }) {
  const root = j(fileInfo.source);

  console.log('transformer: enter');

  root.find(j.JSXOpeningElement).forEach(path => {
    const elementLine = path.node.loc && path.node.loc.start.line;

    if (elementLine === line) {
      console.log(`Matched element on line ${line}`);

      // Update text
      if (changes.text) {
        const parent = path.parent;
        j(parent).find(j.JSXText).replaceWith(j.jsxText(changes.text));
        console.log(`Updated text to: "${changes.text}"`);
      }

      // Update inline style
      if (changes.style) {
        const styleAttr = path.node.attributes.find(attr => attr.name.name === 'style');

        let styleObject = {};

        if (styleAttr && styleAttr.value.expression.properties) {
          styleAttr.value.expression.properties.forEach(prop => {
            styleObject[prop.key.name] = prop.value.value;
          });
        }

        console.log('Original style object:', styleObject);

        // Update color if provided
        if (changes.style.color) {
          styleObject.color = changes.style.color;
        }

        // Handle backgroundColor
        if ('backgroundColor' in changes.style) {
          styleObject.backgroundColor = changes.style.backgroundColor;
        } else {
          delete styleObject.backgroundColor;
        }

        console.log('Updated style object:', styleObject);

        // Rebuild the style attribute
        const styleProps = Object.entries(styleObject).map(([key, value]) =>
          j.objectProperty(j.identifier(key), j.stringLiteral(value))
        );

        // Remove existing style attribute
        path.node.attributes = path.node.attributes.filter(attr => attr.name.name !== 'style');

        // Only add back if we have style properties left
        if (styleProps.length > 0) {
          const newStyleAttr = j.jsxAttribute(
            j.jsxIdentifier('style'),
            j.jsxExpressionContainer(j.objectExpression(styleProps))
          );
          path.node.attributes.push(newStyleAttr);
          console.log('Rebuilt style attribute with:', styleProps.map(p => p.key.name));
        } else {
          console.log('Removed style attribute (no styles remaining)');
        }
      }
    }
  });

  console.log('transformer: exit');
  return root.toSource({ quote: 'single' });
};
