"""冒泡排序演示：相邻元素两两比较，把较大的数逐步"冒泡"到序列右端。"""


def bubble_sort(items: list) -> list:
    """原地升序排序并返回列表，空列表与单元素列表直接返回。"""
    n = len(items)

    for i in range(n - 1):
        # swapped 用于记录本轮是否发生过交换；
        # 若整轮都没有交换，说明已经有序，可以提前结束。
        swapped = False

        # 每完成一轮，最大值就落位在末尾，因此比较范围逐轮缩小。
        for j in range(n - 1 - i):
            if items[j] > items[j + 1]:
                items[j], items[j + 1] = items[j + 1], items[j]
                swapped = True

        if not swapped:
            break

    return items


if __name__ == "__main__":
    data = [5, 1, 4, 2, 8, 0, 3]
    print(f"排序前：{data}")
    print(f"排序后：{bubble_sort(data)}")

    # 边界情况：空列表、单元素、已有序、含重复值。
    for case in ([], [7], [1, 2, 3], [3, 3, 1, 2, 2]):
        print(f"{case} -> {bubble_sort(list(case))}")
