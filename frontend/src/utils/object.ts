export function deepClone<T>(source: T, visited = new WeakMap<object, any>()): T {
  if (source === null || source === undefined) {
    return source
  }

  if (typeof source !== 'object' && typeof source !== 'function') {
    return source
  }

  if (typeof source === 'function') {
    return source
  }

  if (visited.has(source as object)) {
    return visited.get(source as object)
  }

  if (Array.isArray(source)) {
    const clonedArray: any[] = []
    visited.set(source, clonedArray)

    for (let i = 0; i < source.length; i++) {
      clonedArray[i] = deepClone(source[i], visited)
    }

    return clonedArray as T
  }

  if (source instanceof Date) {
    const clonedDate = new Date(source.getTime())
    visited.set(source, clonedDate)
    return clonedDate as T
  }

  if (source instanceof RegExp) {
    const clonedRegExp = new RegExp(source.source, source.flags)
    clonedRegExp.lastIndex = source.lastIndex
    visited.set(source, clonedRegExp)
    return clonedRegExp as T
  }

  if (source instanceof Set) {
    const clonedSet = new Set()
    visited.set(source, clonedSet)

    source.forEach((value) => {
      clonedSet.add(deepClone(value, visited))
    })

    return clonedSet as T
  }

  if (source instanceof Map) {
    const clonedMap = new Map()
    visited.set(source, clonedMap)

    source.forEach((value, key) => {
      clonedMap.set(
        deepClone(key, visited),
        deepClone(value, visited),
      )
    })

    return clonedMap as T
  }

  const clonedObject: Record<string | symbol, any> = {}
  visited.set(source, clonedObject)

  const allKeys = [
    ...Object.getOwnPropertyNames(source),
    ...Object.getOwnPropertySymbols(source),
  ]

  for (const key of allKeys) {
    const descriptor = Object.getOwnPropertyDescriptor(source, key)

    if (descriptor) {
      if (descriptor.value !== undefined) {
        Object.defineProperty(clonedObject, key, {
          ...descriptor,
          value: deepClone(descriptor.value, visited),
        })
      }
      else {
        Object.defineProperty(clonedObject, key, descriptor)
      }
    }
  }

  const prototype = Object.getPrototypeOf(source)
  if (prototype !== null && prototype !== Object.prototype) {
    Object.setPrototypeOf(clonedObject, prototype)
  }

  return clonedObject as T
}

export type MargeArrayStrategy = 'replace' | 'concat' | 'merge'

export type MergeArray<T extends any[], U extends any[], S extends MargeArrayStrategy>
  = S extends 'replace' ? U
    : S extends 'concat' ? [...T, ...U]
      : S extends 'merge' ? T extends [infer T1, ...infer TR]
        ? U extends [infer U1, ...infer UR]
          ? [Merge<T1, U1, S>, ...MergeArray<TR, UR, S>]
          : T
        : U
        : never

export type Merge<T, U, S extends MargeArrayStrategy>
  = T extends any[] ? U extends any[] ? MergeArray<T, U, S> : U
    : T extends object ? U extends object ? {
      [K in keyof T | keyof U]: K extends keyof U ? K extends keyof T
        ? T[K] extends object ? U[K] extends object
          ? Merge<T[K], U[K], S> : U[K] : U[K] : U[K]
        : K extends keyof T ? T[K] : never
    } : T : U

export function deepMerge<T, U, S extends MargeArrayStrategy>(
  target: T,
  source: U,
  options: {
    arrayMerge?: S
    clone?: boolean
  } = {},
): Merge<T, U, S> {
  const {
    arrayMerge = 'merge',
    clone = true,
  } = options

  if (typeof target !== 'object' || target === null) {
    return source as any
  }

  if (typeof source !== 'object' || source === null) {
    return (clone ? deepClone(target) : target) as any
  }

  let result: any
  if (!clone) {
    result = target
  }
  else {
    result = deepClone(target)
  }

  if (Array.isArray(result) && Array.isArray(source)) {
    switch (arrayMerge) {
      case 'concat':
        if (!clone) {
          for (const item of source) {
            result.push(deepClone(item))
          }
        }
        else {
          result.push(...source)
        }
        break

      case 'replace':
        if (!clone) {
          result.length = 0
          for (const item of source) {
            result.push(deepClone(item))
          }
        }
        else {
          result = source
        }
        break

      case 'merge': {
        const maxLength = Math.max(result.length, source.length)
        const mergedArray = []
        for (let i = 0; i < maxLength; i++) {
          if (i < source.length && i < result.length) {
            mergedArray[i] = deepMerge(result[i], source[i], options)
          }
          else if (i < source.length) {
            mergedArray[i] = deepClone(source[i])
          }
          else {
            mergedArray[i] = deepClone(result[i])
          }
        }
        if (!clone) {
          result.length = 0
          for (const item of mergedArray) {
            result.push(item)
          }
        }
        else {
          result = mergedArray
        }
        break
      }
    }

    return result as any
  }

  if (Array.isArray(result) !== Array.isArray(source)) {
    return (clone ? deepClone(source) : source) as any
  }

  if (source instanceof Date || source instanceof RegExp || source instanceof Set || source instanceof Map) {
    return (clone ? deepClone(source) : source) as any
  }

  for (const key in source) {
    if (Object.prototype.hasOwnProperty.call(source, key)) {
      const sourceValue = (source as any)[key]
      const targetValue = result[key]

      if (sourceValue === undefined) {
        continue
      }

      if (
        targetValue !== undefined
        && typeof targetValue === 'object'
        && targetValue !== null
        && typeof sourceValue === 'object'
        && sourceValue !== null
        && !(sourceValue instanceof Date)
        && !(sourceValue instanceof RegExp)
        && !(sourceValue instanceof Set)
        && !(sourceValue instanceof Map)
        && !Array.isArray(sourceValue)
      ) {
        result[key] = deepMerge(targetValue, sourceValue, options)
      }
      else {
        result[key] = clone ? deepClone(sourceValue) : sourceValue
      }
    }
  }

  const sourceSymbols = Object.getOwnPropertySymbols(source)
  for (const sym of sourceSymbols) {
    const sourceValue = (source as any)[sym]
    const targetValue = result[sym]

    if (sourceValue === undefined) {
      continue
    }

    if (
      targetValue !== undefined
      && typeof targetValue === 'object'
      && targetValue !== null
      && typeof sourceValue === 'object'
      && sourceValue !== null
      && !(sourceValue instanceof Date)
      && !(sourceValue instanceof RegExp)
      && !(sourceValue instanceof Set)
      && !(sourceValue instanceof Map)
      && !Array.isArray(sourceValue)
    ) {
      result[sym] = deepMerge(targetValue, sourceValue, options)
    }
    else {
      result[sym] = clone ? deepClone(sourceValue) : sourceValue
    }
  }

  return result as any
}

// export function deepMergeAll<T, U extends any[], S extends MargeArrayStrategy>(
//   target: T,
//   sources: U,
//   options: {
//     arrayMerge?: S
//     clone?: boolean
//   } = {},
// ): Merge<T, U, S> {
//   return sources.reduce((acc, cur) => deepMerge(acc, cur, options), target)
// }
