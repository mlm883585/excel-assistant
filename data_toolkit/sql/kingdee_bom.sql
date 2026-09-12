WITH RootBom AS
(
    SELECT
        b.FID AS BomId,
        b.FNUMBER AS BomVersion,
        m.FMATERIALID AS MaterialId,
        m.FNUMBER AS MaterialNumber,
        ml.FNAME AS MaterialName,
        ml.FSPECIFICATION AS Specification
    FROM dbo.T_ENG_BOM AS b
    INNER JOIN dbo.T_BD_MATERIAL AS m
        ON m.FMATERIALID = b.FMATERIALID
    INNER JOIN dbo.T_BD_MATERIAL_L AS ml
        ON ml.FMATERIALID = m.FMATERIALID
       AND ml.FLOCALEID = 2052
    WHERE m.FNUMBER = :MaterialNumber
      AND b.FNUMBER = :BomVersion
      AND b.FDOCUMENTSTATUS = 'C'
      AND b.FFORBIDSTATUS = 'A'
),
BomRows AS
(
    SELECT
        b.FID AS BomId,
        b.FNUMBER AS BomVersion,
        pm.FNUMBER AS ParentMaterialNumber,
        c.FENTRYID AS EntryId,
        c.FSEQ AS SequenceNumber,
        c.FMATERIALID AS MaterialId,
        cm.FNUMBER AS MaterialNumber,
        cml.FNAME AS MaterialName,
        cml.FSPECIFICATION AS Specification,
        CAST(c.FDOSAGETYPE AS varchar(10)) AS DosageType,
        CAST(c.FNUMERATOR AS decimal(38,10)) AS Numerator,
        CAST(c.FDENOMINATOR AS decimal(38,10)) AS Denominator,
        CAST(c.FFIXSCRAPQTY AS decimal(38,10)) AS FixedScrapQty,
        CAST(c.FSCRAPRATE AS decimal(38,10)) AS ScrapRatePercent,
        c.FMATERIALTYPE AS MaterialType,
        ISNULL(c.FBOMID, 0) AS ChildBomId,
        cb.FNUMBER AS ChildBomVersion,
        cb.FDOCUMENTSTATUS AS ChildDocumentStatus,
        cb.FFORBIDSTATUS AS ChildForbidStatus
    FROM dbo.T_ENG_BOM AS b
    INNER JOIN dbo.T_BD_MATERIAL AS pm
        ON pm.FMATERIALID = b.FMATERIALID
    INNER JOIN dbo.T_ENG_BOMCHILD AS c
        ON c.FID = b.FID
    INNER JOIN dbo.T_BD_MATERIAL AS cm
        ON cm.FMATERIALID = c.FMATERIALID
    INNER JOIN dbo.T_BD_MATERIAL_L AS cml
        ON cml.FMATERIALID = cm.FMATERIALID
       AND cml.FLOCALEID = 2052
    LEFT JOIN dbo.T_ENG_BOM AS cb
        ON cb.FID = c.FBOMID
),
BomTree AS
(
    SELECT
        CAST(1 AS int) AS LevelNumber,
        br.BomId,
        br.BomVersion,
        br.ParentMaterialNumber,
        br.EntryId,
        br.SequenceNumber,
        br.MaterialId,
        br.MaterialNumber,
        br.MaterialName,
        br.Specification,
        br.DosageType,
        br.Numerator,
        br.Denominator,
        br.FixedScrapQty,
        br.ScrapRatePercent,
        br.MaterialType,
        br.ChildBomId,
        br.ChildBomVersion,
        CAST(:RootQty AS decimal(38,10)) AS ParentRequiredQty,
        CAST(
            CASE
                WHEN br.MaterialType = 3 OR br.Denominator = 0 OR br.DosageType NOT IN ('1', '2') THEN NULL
                WHEN br.DosageType = '1' THEN br.Numerator / br.Denominator
                WHEN br.DosageType = '2' THEN CAST(:RootQty AS decimal(38,10)) * br.Numerator / br.Denominator
            END AS decimal(38,10)
        ) AS StandardQty,
        CAST(
            CASE
                WHEN br.MaterialType = 3 OR br.Denominator = 0 OR br.DosageType NOT IN ('1', '2') THEN NULL
                WHEN br.DosageType = '1' THEN
                    (br.Numerator / br.Denominator) * (1 + br.ScrapRatePercent / 100) + br.FixedScrapQty
                WHEN br.DosageType = '2' THEN
                    (CAST(:RootQty AS decimal(38,10)) * br.Numerator / br.Denominator)
                    * (1 + br.ScrapRatePercent / 100) + br.FixedScrapQty
            END AS decimal(38,10)
        ) AS RequiredQty,
        CAST(
            RIGHT(REPLICATE('0', 10) + CAST(br.SequenceNumber AS varchar(10)), 10)
            + '-' + RIGHT(REPLICATE('0', 19) + CAST(br.EntryId AS varchar(19)), 19)
            AS varchar(max)
        ) AS SortPath,
        CAST('/' + CAST(root.BomId AS varchar(20)) + '/' AS varchar(max)) AS BomIdPath,
        CAST(
            CASE
                WHEN br.MaterialType = 3 THEN N'替代件未计算'
                WHEN br.Denominator = 0 THEN N'分母为零，未计算'
                WHEN br.DosageType = '3' THEN N'阶梯用量未计算'
                WHEN br.DosageType NOT IN ('1', '2') THEN N'未知用量类型，未计算'
                WHEN br.ChildBomId <> 0 AND CHARINDEX('/' + CAST(br.ChildBomId AS varchar(20)) + '/', '/' + CAST(root.BomId AS varchar(20)) + '/') > 0 THEN N'检测到循环BOM'
                WHEN br.ChildBomId <> 0 AND (br.ChildBomVersion IS NULL OR br.ChildDocumentStatus <> 'C' OR br.ChildForbidStatus <> 'A') THEN N'子项BOM无效，停止展开'
                WHEN br.ChildBomId = 0 THEN N'正常（叶子）'
                ELSE N'正常'
            END AS nvarchar(100)
        ) AS CalculationStatus,
        CAST(
            CASE
                WHEN br.MaterialType = 3 OR br.Denominator = 0 OR br.DosageType NOT IN ('1', '2') THEN 0
                WHEN br.ChildBomId = 0 THEN 0
                WHEN CHARINDEX('/' + CAST(br.ChildBomId AS varchar(20)) + '/', '/' + CAST(root.BomId AS varchar(20)) + '/') > 0 THEN 0
                WHEN br.ChildBomVersion IS NULL OR br.ChildDocumentStatus <> 'C' OR br.ChildForbidStatus <> 'A' THEN 0
                ELSE 1
            END AS bit
        ) AS CanRecurse
    FROM RootBom AS root
    INNER JOIN BomRows AS br
        ON br.BomId = root.BomId

    UNION ALL

    SELECT
        CAST(parent.LevelNumber + 1 AS int),
        br.BomId,
        br.BomVersion,
        br.ParentMaterialNumber,
        br.EntryId,
        br.SequenceNumber,
        br.MaterialId,
        br.MaterialNumber,
        br.MaterialName,
        br.Specification,
        br.DosageType,
        br.Numerator,
        br.Denominator,
        br.FixedScrapQty,
        br.ScrapRatePercent,
        br.MaterialType,
        br.ChildBomId,
        br.ChildBomVersion,
        CAST(parent.RequiredQty AS decimal(38,10)),
        CAST(
            CASE
                WHEN br.MaterialType = 3 OR br.Denominator = 0 OR br.DosageType NOT IN ('1', '2') THEN NULL
                WHEN br.DosageType = '1' THEN br.Numerator / br.Denominator
                WHEN br.DosageType = '2' THEN parent.RequiredQty * br.Numerator / br.Denominator
            END AS decimal(38,10)
        ),
        CAST(
            CASE
                WHEN br.MaterialType = 3 OR br.Denominator = 0 OR br.DosageType NOT IN ('1', '2') THEN NULL
                WHEN br.DosageType = '1' THEN
                    (br.Numerator / br.Denominator) * (1 + br.ScrapRatePercent / 100) + br.FixedScrapQty
                WHEN br.DosageType = '2' THEN
                    (parent.RequiredQty * br.Numerator / br.Denominator)
                    * (1 + br.ScrapRatePercent / 100) + br.FixedScrapQty
            END AS decimal(38,10)
        ),
        CAST(
            parent.SortPath + '.'
            + RIGHT(REPLICATE('0', 10) + CAST(br.SequenceNumber AS varchar(10)), 10)
            + '-' + RIGHT(REPLICATE('0', 19) + CAST(br.EntryId AS varchar(19)), 19)
            AS varchar(max)
        ),
        CAST(parent.BomIdPath + CAST(br.BomId AS varchar(20)) + '/' AS varchar(max)),
        CAST(
            CASE
                WHEN br.MaterialType = 3 THEN N'替代件未计算'
                WHEN br.Denominator = 0 THEN N'分母为零，未计算'
                WHEN br.DosageType = '3' THEN N'阶梯用量未计算'
                WHEN br.DosageType NOT IN ('1', '2') THEN N'未知用量类型，未计算'
                WHEN br.ChildBomId <> 0 AND CHARINDEX('/' + CAST(br.ChildBomId AS varchar(20)) + '/', parent.BomIdPath + CAST(br.BomId AS varchar(20)) + '/') > 0 THEN N'检测到循环BOM'
                WHEN br.ChildBomId <> 0 AND (br.ChildBomVersion IS NULL OR br.ChildDocumentStatus <> 'C' OR br.ChildForbidStatus <> 'A') THEN N'子项BOM无效，停止展开'
                WHEN parent.LevelNumber + 1 >= 100 AND br.ChildBomId <> 0 THEN N'达到最大递归深度100'
                WHEN br.ChildBomId = 0 THEN N'正常（叶子）'
                ELSE N'正常'
            END AS nvarchar(100)
        ),
        CAST(
            CASE
                WHEN br.MaterialType = 3 OR br.Denominator = 0 OR br.DosageType NOT IN ('1', '2') THEN 0
                WHEN br.ChildBomId = 0 OR parent.LevelNumber + 1 >= 100 THEN 0
                WHEN CHARINDEX('/' + CAST(br.ChildBomId AS varchar(20)) + '/', parent.BomIdPath + CAST(br.BomId AS varchar(20)) + '/') > 0 THEN 0
                WHEN br.ChildBomVersion IS NULL OR br.ChildDocumentStatus <> 'C' OR br.ChildForbidStatus <> 'A' THEN 0
                ELSE 1
            END AS bit
        )
    FROM BomTree AS parent
    INNER JOIN BomRows AS br
        ON br.BomId = parent.ChildBomId
    WHERE parent.CanRecurse = 1
      AND parent.LevelNumber < 100
)
SELECT
    CAST(0 AS int) AS [层级],
    CAST(root.MaterialNumber + N' ' + ISNULL(root.MaterialName, N'') AS nvarchar(1000)) AS [树形物料],
    root.MaterialNumber AS [物料编码],
    root.MaterialName AS [物料名称],
    root.Specification AS [规格型号],
    CAST(NULL AS nvarchar(255)) AS [父项物料编码],
    root.BomVersion AS [所属BOM版本],
    CAST(NULL AS nvarchar(255)) AS [子项BOM版本],
    CAST(N'根节点' AS nvarchar(50)) AS [用量类型],
    CAST(NULL AS decimal(38,10)) AS [分子],
    CAST(NULL AS decimal(38,10)) AS [分母],
    CAST(NULL AS decimal(38,10)) AS [固定损耗],
    CAST(NULL AS decimal(38,10)) AS [变动损耗率%],
    CAST(NULL AS decimal(38,10)) AS [父项需求数量],
    CAST(:RootQty AS decimal(38,10)) AS [标准用量],
    CAST(:RootQty AS decimal(38,10)) AS [需求数量],
    CAST('0000000000-0000000000000000000' AS varchar(max)) AS [层级排序路径],
    CAST(N'根节点' AS nvarchar(100)) AS [计算状态]
FROM RootBom AS root

UNION ALL

SELECT
    tree.LevelNumber,
    CAST(REPLICATE(N'　', tree.LevelNumber) + tree.MaterialNumber + N' ' + ISNULL(tree.MaterialName, N'') AS nvarchar(1000)),
    tree.MaterialNumber,
    tree.MaterialName,
    tree.Specification,
    tree.ParentMaterialNumber,
    tree.BomVersion,
    tree.ChildBomVersion,
    CAST(
        CASE tree.DosageType WHEN '1' THEN N'固定用量' WHEN '2' THEN N'变动用量'
             WHEN '3' THEN N'阶梯用量' ELSE N'未知用量' END
        AS nvarchar(50)
    ),
    tree.Numerator,
    tree.Denominator,
    tree.FixedScrapQty,
    tree.ScrapRatePercent,
    tree.ParentRequiredQty,
    tree.StandardQty,
    tree.RequiredQty,
    tree.SortPath,
    tree.CalculationStatus
FROM BomTree AS tree
ORDER BY [层级排序路径]
OPTION (MAXRECURSION 100)
