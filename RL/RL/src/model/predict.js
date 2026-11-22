function numbers(block, name) {
  const line = block.find((row) => row.startsWith(`${name}=`))
  if (!line) return []
  const value = line.slice(name.length + 1).trim()
  if (!value) return []
  return value.split(/\s+/).map(Number)
}

function integers(block, name) {
  return numbers(block, name).map((value) => value | 0)
}

export function loadModel(text) {
  const trees = text.split(/\r?\nTree=/).slice(1).map((chunk) => {
    const block = chunk.split(/\r?\n/)
    const catCount = Number(block.find((row) => row.startsWith('num_cat='))?.split('=')[1] ?? 0)
    return {
      feature: integers(block, 'split_feature'),
      threshold: numbers(block, 'threshold'),
      decision: integers(block, 'decision_type'),
      left: integers(block, 'left_child'),
      right: integers(block, 'right_child'),
      leaf: numbers(block, 'leaf_value'),
      catBoundaries: catCount ? integers(block, 'cat_boundaries') : [0],
      catThreshold: catCount ? numbers(block, 'cat_threshold') : [],
    }
  })
  return { trees }
}

function bitSet(bits, position) {
  const word = position >>> 5
  if (word >= bits.length) return false
  return ((bits[word] >>> (position & 31)) & 1) === 1
}

function goesLeft(tree, node, value) {
  const decision = tree.decision[node]
  const categorical = (decision & 1) !== 0
  const defaultLeft = (decision & 2) !== 0
  const missingType = (decision >> 2) & 3
  const missing = value == null || Number.isNaN(value)

  if (categorical) {
    if (missing || value < 0) return defaultLeft
    const index = tree.threshold[node] | 0
    const start = tree.catBoundaries[index] ?? 0
    const end = tree.catBoundaries[index + 1] ?? start
    return bitSet(tree.catThreshold.slice(start, end), value | 0)
  }

  let feature = value
  if (missing) {
    if (missingType === 2) return defaultLeft
    feature = 0
  }
  return feature <= tree.threshold[node]
}

function treeScore(tree, features) {
  let node = 0
  const limit = tree.feature.length
  while (node >= 0 && node < limit) {
    const child = goesLeft(tree, node, features[tree.feature[node]]) ? tree.left[node] : tree.right[node]
    if (child < 0) return tree.leaf[-child - 1]
    node = child
  }
  return 0
}

export function predictProbability(model, features) {
  let margin = 0
  for (const tree of model.trees) margin += treeScore(tree, features)
  return 1 / (1 + Math.exp(-margin))
}

export function scoreLabel(probability) {
  if (probability >= 0.55) return 'accepted'
  if (probability <= 0.45) return 'rejected'
  return 'uncertain'
}
