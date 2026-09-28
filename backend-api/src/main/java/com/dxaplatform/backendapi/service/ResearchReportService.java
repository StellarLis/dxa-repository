package com.dxaplatform.backendapi.service;

import com.dxaplatform.backendapi.entity.ProcessingStatus;
import com.dxaplatform.backendapi.entity.Scan;
import com.dxaplatform.backendapi.repository.ScanRepository;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Service;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.List;
import java.util.UUID;

@Service
public class ResearchReportService {

    private static final String[] HEADERS = {
            "path_to_study",
            "study_uid",
            "image_uid",
            "anatomical_region",
            "quality_class",
            "violation_type",
            "processing_status",
            "time_of_processing"
    };

    private final ScanRepository scanRepository;

    public ResearchReportService(ScanRepository scanRepository) {
        this.scanRepository = scanRepository;
    }

    public byte[] createReport(UUID researchId) {
        List<Scan> scans = scanRepository.findByResearchIdOrderByUploadedAtDesc(researchId);

        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet("Исследование");
            Row header = sheet.createRow(0);
            for (int column = 0; column < HEADERS.length; column++) {
                header.createCell(column).setCellValue(HEADERS[column]);
            }

            for (int index = 0; index < scans.size(); index++) {
                writeScanRow(sheet.createRow(index + 1), scans.get(index));
            }

            workbook.write(output);
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("Не удалось сформировать отчёт", exception);
        }
    }

    private void writeScanRow(Row row, Scan scan) {
        setString(row, 0, scan.getOriginalFilename());
        setString(row, 1, scan.getStudyUid());
        setString(row, 2, scan.getImageUid());
        setString(row, 3, scan.getAnatomicalRegion());
        if (scan.getQualityClass() != null) {
            row.createCell(4).setCellValue(scan.getQualityClass());
        }
        setString(row, 5, scan.getViolationType());
        row.createCell(6).setCellValue(
                scan.getProcessingStatus() == ProcessingStatus.SUCCESS ? "Success" : "Failure"
        );
        if (scan.getTimeOfProcessing() != null) {
            row.createCell(7).setCellValue(scan.getTimeOfProcessing());
        }
    }

    private void setString(Row row, int column, String value) {
        if (value != null) {
            row.createCell(column).setCellValue(value);
        }
    }
}