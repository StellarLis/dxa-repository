package com.dxaplatform.backendapi.service;

import com.dxaplatform.backendapi.dto.ScanSummaryResponse;
import com.dxaplatform.backendapi.dto.UploadResponse;
import com.dxaplatform.backendapi.entity.ProcessingStatus;
import com.dxaplatform.backendapi.entity.Research;
import com.dxaplatform.backendapi.entity.Scan;
import com.dxaplatform.backendapi.entity.User;
import com.dxaplatform.backendapi.exception.ApiException;
import com.dxaplatform.backendapi.kafka.KafkaPublishException;
import com.dxaplatform.backendapi.kafka.ScanProcessingMessage;
import com.dxaplatform.backendapi.kafka.ScanProducerService;
import com.dxaplatform.backendapi.repository.ScanRepository;
import com.dxaplatform.backendapi.repository.UserRepository;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/**
 * Оркестрирует приём загрузки (раздел 4.3-4.4 ТЗ) в ДВА чётких этапа:
 *
 * 1. Валидация всех файлов + сохранение Job/Scan в БД как QUEUED -- делегировано
 *    в ScanJobPersistenceService, единая транзакция (см. её javadoc про self-invocation).
 * 2. Публикация в Kafka (медленный сетевой вызов) -- ВНЕ транзакции. Если
 *    публикация для конкретного файла не удалась, помечаем именно ЕГО как
 *    FAILED отдельным лёгким обновлением, не трогая остальные файлы батча.
 *
 * Так транзакция с БД не держится открытой во время медленного/нестабильного
 * похода в Kafka, а частичный отказ одного файла в батче не ломает остальные.
 */
@Service
public class ScanUploadService {

    private static final Logger log = LoggerFactory.getLogger(ScanUploadService.class);
    private static final String REQUIRED_EXTENSION = ".dcm";
    private static final byte[] DICM_MAGIC = {'D', 'I', 'C', 'M'};
    private static final int DICM_MAGIC_OFFSET = 128; // преамбула DICOM -- 128 байт, затем "DICM" (стандарт PS3.10)

    private final ResearchService researchService;
    private final ScanJobPersistenceService persistenceService;
    private final ScanRepository scanRepository;
    private final UserRepository userRepository;
    private final ScanProducerService scanProducerService;

    public ScanUploadService(
            ResearchService researchService,
            ScanJobPersistenceService persistenceService,
            ScanRepository scanRepository,
            UserRepository userRepository,
            ScanProducerService scanProducerService
    ) {
        this.researchService = researchService;
        this.persistenceService = persistenceService;
        this.scanRepository = scanRepository;
        this.userRepository = userRepository;
        this.scanProducerService = scanProducerService;
    }

    public UploadResponse upload(UUID researchId, AuthenticatedUser authUser, List<MultipartFile> files) {
        if (files == null || files.isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Не выбрано ни одного файла");
        }

        Research research = researchService.findOwnedOrAdmin(researchId, authUser);
        User requestedBy = userRepository.getReferenceById(authUser.id());

        // этап 0: читаем и валидируем ВСЕ файлы ДО единой записи в БД -- если
        // хотя бы один файл невалиден, весь запрос отклоняется целиком (400),
        // ничего не создаётся
        List<ScanJobPersistenceService.ValidatedFile> validatedFiles = new ArrayList<>();
        for (MultipartFile file : files) {
            validatedFiles.add(validate(file));
        }

        List<ScanJobPersistenceService.PersistedFile> persisted =
                persistenceService.persistJobAndScans(research, requestedBy, validatedFiles);

        List<ScanSummaryResponse> summaries = publishAll(persisted);

        return new UploadResponse(persisted.get(0).job().getId(), summaries);
    }

    private ScanJobPersistenceService.ValidatedFile validate(MultipartFile file) {
        String filename = file.getOriginalFilename();
        if (filename == null || !filename.toLowerCase(Locale.ROOT).endsWith(REQUIRED_EXTENSION)) {
            throw new ApiException(HttpStatus.BAD_REQUEST,
                    "Файл '" + filename + "' должен иметь расширение .dcm");
        }

        byte[] bytes;
        try {
            bytes = file.getBytes();
        } catch (IOException e) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Не удалось прочитать файл '" + filename + "'");
        }

        if (!looksLikeDicom(bytes)) {
            throw new ApiException(HttpStatus.BAD_REQUEST,
                    "Файл '" + filename + "' не похож на валидный DICOM (нет сигнатуры DICM)");
        }

        return new ScanJobPersistenceService.ValidatedFile(filename, bytes);
    }

    private boolean looksLikeDicom(byte[] bytes) {
        if (bytes.length < DICM_MAGIC_OFFSET + DICM_MAGIC.length) {
            return false;
        }
        for (int i = 0; i < DICM_MAGIC.length; i++) {
            if (bytes[DICM_MAGIC_OFFSET + i] != DICM_MAGIC[i]) {
                return false;
            }
        }
        return true;
    }

    private List<ScanSummaryResponse> publishAll(List<ScanJobPersistenceService.PersistedFile> persisted) {
        List<ScanSummaryResponse> summaries = new ArrayList<>();

        for (ScanJobPersistenceService.PersistedFile pf : persisted) {
            Scan scan = pf.scan();
            ScanProcessingMessage message = new ScanProcessingMessage(
                    scan.getId(),
                    pf.job().getId(),
                    scan.getResearch().getId(),
                    pf.job().getRequestedBy().getId(),
                    scan.getOriginalFilename(),
                    Base64.getEncoder().encodeToString(pf.fileBytes())
            );

            try {
                scanProducerService.publish(message);
                summaries.add(new ScanSummaryResponse(
                        scan.getId(), scan.getOriginalFilename(), scan.getProcessingStatus().name()
                ));
            } catch (KafkaPublishException e) {
                log.error("Публикация не удалась для scan={}, помечаю как FAILED", scan.getId(), e);
                scan.setProcessingStatus(ProcessingStatus.FAILED);
                scan.setErrorMessage("Не удалось поставить файл в очередь на обработку: " + e.getMessage());
                scanRepository.save(scan);
                summaries.add(new ScanSummaryResponse(
                        scan.getId(), scan.getOriginalFilename(), scan.getProcessingStatus().name()
                ));
            }
        }
        return summaries;
    }
}
