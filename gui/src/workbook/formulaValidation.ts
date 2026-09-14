import type { Snapshot } from './adapter'

type Dependency = { treeId: number; children: number[]; unitId: string; subUnitId: string; row: number; column: number }

/** Univer 0.25.1 iterates circular formulas once and may return zero.
 * Remove acyclic dependency leaves; remaining nodes are cycles or their dependents.
 * Work on the application's snapshot, never change formula text or invent a cache.
 */
export function markCircularFormulas(snapshot: Snapshot, trees: Dependency[], ids: Map<string,string>) {
  const nodes=new Map(trees.filter(t=>t.unitId===snapshot.id).map(t=>[t.treeId,t]))
  const remaining=new Map<number,number>(), dependents=new Map<number,number[]>(), queue:number[]=[]
  for(const tree of nodes.values()) {
    const dependencies=tree.children.filter(id=>nodes.has(id))
    remaining.set(tree.treeId,dependencies.length)
    if(!dependencies.length) queue.push(tree.treeId)
    for(const id of dependencies) {if(!dependents.has(id))dependents.set(id,[]);dependents.get(id)!.push(tree.treeId)}
  }
  for(let i=0;i<queue.length;i++) for(const id of dependents.get(queue[i])||[]) {
    const degree=remaining.get(id)!-1;remaining.set(id,degree);if(!degree)queue.push(id)
  }
  const sheets=new Map(snapshot.sheets.map(s=>[s.id,s]))
  for(const [id,degree] of remaining) if(degree>0) {
    const tree=nodes.get(id)!, sheet=sheets.get(ids.get(tree.subUnitId)||tree.subUnitId)
    const cell=sheet?.cells[`${tree.row},${tree.column}`]
    if(cell?.formula) Object.assign(cell,{value:'#CYCLE!',type:'error',result_state:'error'})
  }
}
