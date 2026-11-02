"""插入排序演示：像整理扑克牌一样，把每个新元素插入到左侧已排好序的区间中。"""


def insertion_sort(items: list) -> list:
    """原地升序排序并返回列表，空列表与单元素列表直接返回。"""
    for i in range(1, len(items)):
        # current 是待插入的牌；已排序区间为 items[0:i]。
        current = items[i]
        j = i - 1

        # 从右往左扫描已排序区间，把大于 current 的元素逐个后移，
        # 直到找到第一个不大于 current 的元素，空出的位置就是插入点。
        while j >= 0 and items[j] > current:
            items[j + 1] = items[j]
            j -= 1

        items[j + 1] = current

    return items


if __name__ == "__main__":
    data = [5, 1, 4, 2, 8, 0, 3]
    print(f"排序前：{data}")
    print(f"排序后：{insertion_sort(data)}")

    # 边界情况：空列表、单元素、已有序、含重复值、逆序。
    for case in ([], [7], [1, 2, 3], [3, 3, 1, 2, 2], [9, 5, 3, 1]):
        print(f"{case} -> {insertion_sort(list(case))}")
